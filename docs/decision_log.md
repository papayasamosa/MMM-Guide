# Decision Log

Format: Date, Decision, Reason, Alternatives considered, Impact, Owner, Status.

---

**Date:** 2026-07-31
**Decision:** Approve REQ-CURVE-001 (official response curve authority and evidence contract)
for implementation, with: `curve_publication` approval mandatory for official artifact
status (downstream uses independently gated); Option B architecture (`CurveBankEntry` stays
a parameter-snapshot registry; a separate canonical evaluated artifact becomes the official
curve); incremental-eta share retained as an explicitly approved, versioned component
reporting convention (not a causal decomposition); a four-concept artifact lifecycle /
current-use status vocabulary separate from `OUTCOME_APPROVAL_STATUSES`; approved cost
mappings required for all monetary curves including exploratory; and current-use
revalidation for every official use while historical exports remain loadable/viewable but
labelled not-current.
**Reason:** The PR 93A draft was corrected by PR 94A (PR #95) to address all five post-merge
review findings on #93 and additional defects; the corrected requirement defines the
governance and evidence contract for official response curves without changing any
mathematics or existing behaviour. Approval authorises the follow-on implementation sequence
(PR 95A-95F, then 96A/96B, 97A).
**Alternatives considered:** Options A and C from `docs/curve_authority_gap_analysis.md`
(rejected in favour of Option B); Shapley and explicit-counterfactual component
decompositions (deferred — a separate approved causal method is still required before any
component row may be labelled a causal effect); reusing `OUTCOME_APPROVAL_STATUSES` as an
artifact-status vocabulary (rejected — kept separate).
**Impact:** REQ-CURVE-001 status changes to `approved_for_implementation` in
`docs/approved_requirements/index.json`; currently-implemented invariant tests are
registered as `required_tests`; no application or modelling code changes in this decision.
**Owner:** Product / Analytics + Platform engineering.
**Status:** Accepted (PR 94B).
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

## G2A -- canonical posterior curve and economics engine

**Decision:** One long-form, component-level posterior draw table is now the
source of truth for response curves and economics. Shared and
market-specific fits use the same contract. CPA and ROI are calculated by
draw, totals aggregate draws before summarisation, and invalid economics are
represented by `NaN` plus a machine-readable status rather than misleading
infinities. Standard views cover segments, products, markets, FH net
bill-through, direct versus halo, headline-approved, and planning-eligible
components. Draws, summaries, and a versioned schema have an open Parquet/JSON
curve-bank export.

The legacy pathway review now permits a direct/cross-product reclassification
for the same outcome/channel only when the analyst explicitly confirms it.
Exactly one reviewed equation component or one exclusion must replace each
reconstructed relationship. Source-product values are labelled inferred.
Reviewer, timestamp, note, source run, change summary, invalidation state, and
replacement refit run are persisted separately from headline approval.

**Scope:** G2A is core calculation, audit, persistence, and test infrastructure.
Response horizons (G2B), year-on-year decomposition (G2C), the decision-ready
dashboard (G2D), and the dynamic planner remain separate work.

## G2A.1 -- outcome-scale counterfactual correction

**Correction:** G2A's initial `response` field was a media contribution to the
log mean, not an outcome count. Canonical response now replays the complete
shared or market-specific prediction function under an explicit business
context and subtracts the configured channel counterfactual. Marginal response
uses a finite difference through that same full-link prediction.

Component rows retain response decomposition and log-scale media terms but
have no CPA/ROI without cost allocation. Channel aggregation counts spend
once. Cross-channel marginal economics are blocked unless an explicit
portfolio path and perturbation vector define the budget direction. Observed
support is actual or unknown, current spend is governed by a named method,
multi-market currency conversion requires ISO/FX metadata, and reconciliation
diagnostics are part of the curve contract.

**Scope:** This is the mathematical correction to G2A only. Response horizons,
year-on-year reporting, stakeholder UI, and dynamic planning remain deferred.

## Coverage authority reconciliation (Work Package A)

**Date:** 2026-08-11
**Decision:** Reconcile `docs/specification_authority.md` and
`docs/approved_requirements/REQ-COVERAGE-001.md` with what PRs #151-#159
actually implemented, without rewriting either document's historical
approval-time text as though the capability existed on 2026-08-09.
**Reason:** Both documents are implementation authority that coding agents
are instructed to treat as current fact (`AGENTS.md` requirements-authority
hierarchy). By 2026-08-11 they still stated "No source/coverage-matrix
domain objects, join diagnostics, frequency-conversion contracts, or
market-aware prepared-frame representation are implemented yet" and
"Capability status: Not implemented", even though `core.coverage`,
`data.pipeline.join_sources_with_diagnostics`, `core.market_data_
capability`, the Data Coverage review UI, and the pre-fit prior-predictive
binding had all since been merged (PRs #151-#159). Leaving this
uncorrected risks a future coding agent re-implementing already-delivered
work, or trusting a stale "not implemented" status over the actual code.
**Alternatives considered:** Rewriting the original "Capability status: Not
implemented" sentence and the implementation-gaps table row in place to
read as already-implemented (rejected - would misrepresent what was true
at approval time and erase the historical record of incremental delivery).
Leaving the documents as-is and relying on this decision-log entry alone
to correct the record (rejected - `AGENTS.md` and `docs/specification_
authority.md` are the documents coding agents are told to read directly;
an easily-missed decision-log entry is not an adequate substitute).
**Impact:** `docs/specification_authority.md`'s REQ-COVERAGE-001
implementation-gaps row now names the specific delivered capabilities and
PR range while keeping its State column unchanged ("Requirement exists but
capability incomplete" - `FR-MOD-015` and several other invariants remain
genuinely unresolved); REQ-COVERAGE-001 gains a bullet in "Approved
requirement records already implemented" alongside `REQ-GRAPH-001`/
`REQ-SEARCH-001`, the same established pattern for an approved record with
a documented, narrower-than-full capability boundary. `docs/approved_
requirements/REQ-COVERAGE-001.md`'s "Capability status" section gains a
dated 2026-08-11 status update *in addition to*, not instead of, the
2026-08-09 approval-time text; two "Unresolved decisions" bullets
(domain-object shape, structural-zero governance mechanism) are marked
resolved with their delivering PR. No `ancestry_mmm/` source, schema, or
model behaviour changes.
**Owner:** Platform engineering.
**Status:** Accepted; implemented in this PR.

## Coverage official-use gate (Work Package B)

**Date:** 2026-08-11
**Decision:** Add `core.market_data_capability.check_market_channel_capability`'s
result as an optional, non-waivable `market_channel_capability` validation-policy
gate that participates in the existing `evaluate_approval_readiness`/
`create_policy_backed_model_approval` mechanism, rather than inventing a
bespoke governance rule or a new waiver system. Whether the gate is active is
entirely policy-driven - this app ships no default `ThresholdPolicy` (PR
79A/WP7), so nothing is forced on an existing project.
**Reason:** REQ-COVERAGE-001 S6's capability report was informational only
(`pages/04_Model_Config.py`, `pages/06_Diagnostics.py`) - nothing stopped a
policy-backed official approval from being granted for a market/channel
combination the current rectangular engine cannot validly support. The
existing `ValidationGate(waivable=False, blocking=True, required=True)`
mechanism already provides exactly the fail-closed, non-waivable semantics
needed, and reusing it means the gate is automatically enforced everywhere
approval is created or re-verified (`core.approval.
create_policy_backed_model_approval`/`require_matching_approval`,
`core.persistence.verify_imported_approval`) with zero changes to those
modules.
**Alternatives considered:** A bespoke approval-blocking check hard-coded
into `06_Diagnostics.py`'s Approve button (rejected - Streamlit-only,
contradicts the brief's explicit "do not implement the gate only in
Streamlit" requirement, and duplicates logic the policy/readiness system
already generalises). Forcing this gate into every policy by default
(rejected - this app has deliberately shipped no default policy since PR
79A; inventing one now, or special-casing this one gate to bypass that
convention, is a bigger decision than this package's scope).
**Correction (same PR, pre-merge):** an automated review caught two P1
defects in the initial version: (1) the gate's evaluator had the opposite
boolean polarity from `classify_boolean_gate`'s default, so a policy
configured without `expected_state=True` would silently treat an
*unsupported* result as passing - fixed by adding
`EvaluatorMeta.required_expected_state`, enforced by `validate_gate_config`.
(2) the capability section trusted `check_market_channel_capability`'s
per-cell result even when the coverage matrix was stale relative to the
currently joined data (it never reads the joined data itself) - fixed by
threading `coverage_matrix_built_against_fingerprint`/
`joined_dataframe_fingerprint` through `DiagnosticsInput` and forcing
`supported=False` when they are absent or mismatched, mirroring the
existing informational freshness check on `pages/04_Model_Config.py` but
making it authoritative for the gate.
**Impact:** `DiagnosticsArtefact` schema v5 → v6 (`market_channel_
capability` section); `core.validation_policy` gains the
`market_channel_capability` evaluator/alias/`required_expected_state`
mechanism; `application.validation_service` reads the new section;
`pages/06_Diagnostics.py` threads the coverage matrix and both freshness
fingerprints through. No `FR-MOD-015` model-engine mathematics changed.
Deferred to a later phase: generalising beyond market x channel to every
fit-consumed variable, and dedicated AppTest/Playwright coverage of the
visible approval-blocking journey.
**Owner:** Platform engineering.
**Status:** Accepted; implemented in PR #161.

## Canonical-calendar and mixed-frequency alignment contracts (Work Package C)

**Date:** 2026-08-11
**Decision:** Add `core.frequency_alignment` as a pure-contracts module -
`AlignmentSpecification` (the versioned, typed conversion decision REQ-
COVERAGE-001 S4 requires), a conversion-method registry that is left
genuinely empty, publication-leakage/definition-break/support-boundary
checks, and `resolve_canonical_calendar` (fails closed with
`CalendarResolutionRequiredError` rather than inferring a calendar from raw
source intersection). Not wired into `data.pipeline`, `data.loader`, or any
Streamlit page in this PR.
**Reason:** REQ-COVERAGE-001 S4 authorises variable-class-specific
conversion semantics but approves no concrete method for any class ("Out of
scope": "any specific imputation formula, interpolation kernel, or default
fill method not named in S4"). This repository also has no governed
project-calendar configuration object anywhere (`core.market_config.
MarketSpecConfig` has no `project_start`/`project_end`/target-frequency
field) - `resolve_canonical_calendar` therefore cannot resolve anything
without the caller supplying an explicit governed decision, and raises
naming exactly what is missing rather than guessing (e.g. from whichever
source has the shortest history). This mirrors `core.coverage`'s own
precedent of shipping pure vocabulary/contracts before any dependent
package wires them into the live pipeline (see that module's "Work Package
3 Phase 1 of N" docstring).
**Alternatives considered:** Wiring `resolve_canonical_calendar`/
`evaluate_alignment_request` into `data.pipeline.join_sources_with_
diagnostics` or the Transform Pipeline page now (rejected - with the method
registry genuinely empty, every mixed-frequency variable would become
permanently blocked with no path forward until a method is approved,
trading one silent behaviour for an equally unhelpful one; the explicit
join-mode/join-loss diagnostics PR #157 already delivered keep working
unchanged). Choosing a default project calendar from existing session
state or the join's own date range (rejected - REQ-COVERAGE-001 S1's "never
truncate to the narrowest common window" / "never infer a calendar from
whichever source has the shortest history" apply here exactly as they do to
join intersection).
**Impact:** New `core.frequency_alignment` module and
`ancestry_mmm/tests/test_frequency_alignment.py` (34 tests). No
`ancestry_mmm/` behaviour changes outside this new module - `data.pipeline`,
`core.coverage`, and every Streamlit page are unchanged.
**Unresolved decisions carried forward:** where a project's governed
calendar configuration should actually live (a new `MarketSpecConfig`
field, a project-level setting, or elsewhere) - this record does not invent
it; any concrete frequency-conversion method for any variable class (this
brief's Work Package D); wiring this module into official data preparation
once at least one method is approved.
**Owner:** Platform engineering.
**Status:** Accepted; implemented in PR #162.

## Frequency-conversion method decision options (Work Package D)

**Date:** 2026-08-11
**Decision:** Publish `docs/frequency_conversion_method_options.md`, a decision-support survey
of candidate frequency-conversion methods for each of `core.coverage.VARIABLE_CLASSES`'s five
variable classes (flow/count, stock/level, rate/index, survey/measurement, event/flag),
assessed against nine dimensions (constancy assumption, reconciliation, publication-lag
behaviour, revision-vintage behaviour, boundary behaviour, uncertainty implication, backtest
reconstruction implication, artificial-variation risk, attenuation/overconfidence risk) per
the brief's Work Package D. No candidate is marked approved; nothing is registered in
`core.frequency_alignment`'s conversion-method registry.
**Reason:** REQ-COVERAGE-001 S4 authorises variable-class-specific conversion semantics but
explicitly does not approve one method for any class, and forbids inventing "any specific
imputation formula, interpolation kernel, or default fill method not named in S4." A coding
agent choosing a method unilaterally - even a defensible one - would be exactly the invented
business/statistics decision root `AGENTS.md`'s requirements-authority hierarchy prohibits.
Mirrors the existing `docs/curve_authority_gap_analysis.md` precedent: a plain options-analysis
document that is the evidence base for a future human approval, not itself a `REQ-*` record.
**Alternatives considered:** Selecting one "reasonable default" method per class now (e.g.
step/LOCF everywhere) to unblock `core.frequency_alignment`'s pipeline wiring sooner (rejected
- explicitly forbidden by REQ-COVERAGE-001 S4's "Out of scope", and every candidate surveyed
carries real, class-specific tradeoffs that a reviewer with domain context should weigh, not a
coding agent). Waiting to produce this document until a modelling contract already exists
(rejected - the brief's Work Package D exists precisely to give a reviewer the structured
options needed to *reach* that contract).
**Impact:** New `docs/frequency_conversion_method_options.md`. `docs/approved_requirements/
REQ-COVERAGE-001.md`'s "Unresolved decisions" gains a pointer to it. No `ancestry_mmm/`
source, schema, or model behaviour changes - `core.frequency_alignment`'s registry remains
empty and every real alignment request still resolves to
`unsupported_no_approved_method`.
**Owner:** Platform engineering.
**Status:** Accepted; implemented in PR #163.

## Data Input Contract approval (Work Package E gate)

**Date:** 2026-08-11
**Decision:** Adopt the "Ancestry MMM Data Input Contract and Repository Alignment Review"
(external, previously Draft) as approved, per explicit user approval in-session, and translate
it into repository authority as `REQ-DATAIN-001`: three required logical source domains
(Outcomes; Activity and Media; Context and External Factors), one optional domain (Experiment
Evidence), and `pooling_group_id` as a stable cross-market activity identity that never
automatically forces parameter pooling.
**Reason:** The task-specific brief explicitly required this approval gate before implementing
any of the amendment's draft-only decisions - a coding agent inventing this business decision
unilaterally, or silently promoting draft text into approved behaviour, is exactly what root
`AGENTS.md`'s requirements-authority hierarchy prohibits. The user supplied that approval
directly, in this session, including two specific clarifications (the exact three required
domains, and that `pooling_group_id` must not imply pooling) that resolve what would otherwise
have been ambiguous in the summarised external document.
**Alternatives considered:** Treating the user's approval as covering only the two explicitly
clarified points, leaving the rest of the summarised proposal (arbitrary physical file counts
per domain, market-as-row, separate spend/response-unit semantics, paid/owned/earned unification,
native-frequency upload acceptance, template packs) still in draft (rejected - the user's first
sentence approves "the ... Review as the approved source-input contract" as a whole; the two
clarifications read as resolving specific ambiguities within that approval, not narrowing its
scope). Implementing the external document's literal example schema verbatim (rejected -
REQ-DATAIN-001 explicitly requires implementation "against current architecture," mirroring
`REQ-COVERAGE-001`'s own precedent that existing registries like `core.media_costs`/
`core.media_units`/`ActivityDefinition.activity_ownership` must not be duplicated).
**Impact:** New `docs/approved_requirements/REQ-DATAIN-001.md`, `index.json` entry, `README.md`
category. No `ancestry_mmm/` source, schema, or model behaviour changes in this record itself -
dependent, separately-scoped implementation packages (Work Package E1-E6) build against it.
**Owner:** Data Science / Platform engineering (user-approved).
**Status:** Accepted; implemented in PR #164.

## Logical source domains (Work Package E1)

**Date:** 2026-08-11
**Decision:** `core.coverage.SourceDefinition` gains a required `logical_domain` field
validated against the four `REQ-DATAIN-001` domains (Outcomes, Activity and Media, Context
and External Factors, Experiment Evidence). A source with no `SourceDefinition` at all
resolves to the explicit "unclassified" state via `resolve_source_logical_domain`, never a
guessed domain. `pages/01_Data_Upload.py` gains a domain selector on the upload tab and
displays each loaded source's resolved domain; the synthetic demo's own source names (media,
outcomes, controls) map unambiguously onto their domains. `core.persistence`/
`application.project_service` gain `source_definitions` export/import, mirroring
`source_versions` exactly (`resolve_imported_source_definitions`).
**Reason:** `REQ-DATAIN-001` deferred the concrete domain-object shape and legacy-migration
rule to this package. `SourceDefinition` already existed (`core.coverage`) as an unused,
unwired dataclass for exactly this purpose ("a named, stable source identity... distinct from
any one upload of it") - extending it, rather than inventing a second object or a
session-state-only field, avoids duplicating `SourceVersion`'s established
identity/provenance pattern and gets versioned export/import for free by mirroring that
pattern precisely.
**Alternatives considered:** A new, separate domain-object type instead of extending
`SourceDefinition` (rejected - `SourceDefinition` was defined for exactly this "stable source
identity" purpose and was simply never wired up; a second object would duplicate it).
Defaulting an unclassified legacy source into one of the four domains by inference (e.g. from
its name) (rejected - `REQ-COVERAGE-001`'s "never guess" precedent applies here identically;
an explicit "Unclassified" state is honest, an inferred default is not).
**Impact:** `core.coverage.SourceDefinition`/`LOGICAL_SOURCE_DOMAINS`/
`resolve_source_logical_domain` (new); `core.persistence.resolve_imported_source_definitions`
and `export_project`/`import_project` `source_definitions` wiring;
`application.project_service.ProjectExportInput.source_definitions`;
`pages/01_Data_Upload.py`'s domain selector and display;
`pages/09_Project_Export.py`'s export/import wiring. Two `REQ-DATAIN-001` "Unresolved
decisions" marked resolved. No existing schema/model/persisted-artefact behaviour changes -
`SourceDefinition` was previously unused everywhere.
**Owner:** Platform engineering.
**Status:** Accepted; implemented in PR #165.

## Activity source-column mapping (Work Package E2)

**Date:** 2026-08-11
**Decision:** Add `core.media_units.resolve_activity_source_mapping(activity, market,
market_spec_config) -> ActivitySourceMapping`, resolving an `ActivityDefinition`'s
model-input, spend, and response-unit columns as three distinct fields for one
caller-supplied market, by looking up its channel's existing
`core.market_config.ChannelMediaUnitConfig` (`spend_column`/`response_unit_column`,
already separated at market x channel grain). No new persisted field was added to
`ActivityDefinition` itself.
**Reason:** REQ-DATAIN-001 item 5 requires these three semantics to be distinct,
explicitly-mapped fields, and requires integrating with `core.media_units`/`core.media_costs`
rather than duplicating them. Investigation found `ChannelMediaUnitConfig` already fully
satisfies the spend/response-unit half of that requirement (it has separated these two fields
since the market-specific redesign, docs/media_units_and_inflation.md) - what was actually
missing was a governed link from `ActivityDefinition` (market x activity_id grain, finer than
`ChannelMediaUnitConfig`'s market x channel grain, since "multiple activities may share a
channel when they have distinct model-input columns") to that existing registry. A resolution
helper closes that gap without inventing a second mapping surface.
**Alternatives considered:** Adding `spend_column`/`response_unit_column` fields directly to
`ActivityDefinition` (rejected - `REQ-DATAIN-001` explicitly requires integrating with
existing registries "rather than inventing a second, competing mapping surface"; two
activities sharing a channel would also need those fields to agree with the channel's own
config or the model becomes internally inconsistent about a shared channel's units - a
resolution function reading the single channel-level source of truth avoids that entirely).
Resolving from `activity.market` directly instead of a caller-supplied market (rejected - an
activity's own `market` may be `"*"` (all markets), which does not correspond to any single
`ChannelMediaUnitConfig` row; mirrors `ActivityDefinition.applies_to_market`'s existing
one-market-at-a-time pattern).
**Impact:** New `core.media_units.ActivitySourceMapping`/`resolve_activity_source_mapping`.
One `REQ-DATAIN-001` "Unresolved decision" marked resolved. No existing schema, persisted
field, or model behaviour changes.
**Owner:** Platform engineering.
**Status:** Accepted; implemented in PR #166.

## pooling_group_id on ActivityDefinition (Work Package E3)

**Date:** 2026-08-11
**Decision:** Add `ActivityDefinition.pooling_group_id: str | None = None` (schema v2 → v3),
per the user's explicit approval: a stable cross-market activity identity that must never
automatically force parameter pooling. Deliberately excluded from `_INVALIDATION_MATRIX`
(no refit/rebuild flag on edit), `activity_fit_fingerprint` (never influences what is fit),
and - per the 2026-08-11 correction below - `activity_definitions_fingerprint` too.
**Reason:** The user's own approval text was explicit and unambiguous on this exact point -
"pooling_group_id should be used as the stable cross-market activity identity, without
automatically forcing pooling" - so the implementation choice was mechanical (add the field,
wire it to never touch modelling code) rather than a fresh design decision. Excluding it from
the invalidation matrix specifically encodes the "never forces/implies pooling" invariant as
code, not merely as a comment - if editing it prompted a refit/rebuild, that would itself
contradict the approved invariant by implying the field has a fit-relevant effect.
**Alternatives considered:** Including `pooling_group_id` in `_INVALIDATION_MATRIX` with all
`False` impacts (rejected as redundant with simply omitting it - the matrix already treats an
absent key as "no invalidation" via `activity_invalidation`'s `changed` computation, which
only iterates `_INVALIDATION_MATRIX`'s own keys).
**Impact:** `ActivityDefinition.pooling_group_id`/`schema_version=3`. One `REQ-DATAIN-001`
"Unresolved decision" marked resolved. No existing persisted-field values change meaning; a
legacy payload with no `pooling_group_id` key resolves to `None`, never fabricated.
**Owner:** Platform engineering (field shape/behaviour), Data Science (user-approved
semantics).
**Status:** Accepted; implemented in PR #167.

**Correction (2026-08-11, same-PR review fix):** The original decision above kept
`pooling_group_id` inside `activity_definitions_fingerprint`'s hashed payload, reasoned as "a
distinct, broader governance/audit signal, not a refit trigger." PR #167 review verified this
was factually wrong: `activity_definitions_fingerprint` is not a soft audit signal - it is a
hard blocking gate, read by `CurveArtifactService.validate_for_use` (raises
`CurveUseNotAuthorizedError` on mismatch) and `core.optimization`'s scenario-staleness check
(marks a saved scenario `"stale"` on mismatch). Leaving `pooling_group_id` in that hash meant a
pure identity edit - changing nothing fit-relevant - would silently invalidate existing curve
artifacts and mark scenarios stale, contradicting the approved "never forces, implies, or
defaults to" invariant just as directly as including it in `_INVALIDATION_MATRIX` would have.
Fixed by excluding `pooling_group_id` from `activity_definitions_fingerprint`'s hashed payload,
the same way it was already excluded from `activity_fit_fingerprint`. See
`docs/approved_requirements/REQ-DATAIN-001.md`'s E3 resolved-decision note for the corrected
description.

## Governed activity taxonomy (Work Package 1)

**Date:** 2026-08-13
**Decision:** Extend `ActivityDefinition` (schema v3 → v4) with explicit
`funnel_stage` and optional `marketing_objective` fields. `funnel_stage` uses
the closed vocabulary `brand_upper`, `mid_funnel`, `performance_lower`,
`cross_funnel`, `not_applicable`, and `unclassified`; missing legacy values
migrate to `unclassified` and an empty objective without name/platform/source
inference. The Media Mapping editor exposes both fields and the existing
`pooling_group_id`, while preserving platform, campaign, product, message and
shared reporting-channel semantics.
**Reason:** Work Package 1 requires a reproducible reporting taxonomy while
the repository's existing `ActivityDefinition` already owns the activity
identity and persistence contract. Funnel stage is descriptive metadata, not
a causal role, graph edge, model prior, coefficient, planning permission, or
optimisation rule. `marketing_objective` remains a normalized string with UI
suggestions rather than an invented closed business enum.
**Alternatives considered:** Inferring funnel stage from channel, platform,
campaign type, message type or source-column names (rejected - those mappings
are ambiguous and the approved brief explicitly requires explicit
classification). Adding taxonomy fields to `ModelSpec.channels` or making
them fit-relevant (rejected - `channel` is a reporting roll-up and taxonomy
changes do not change model equations). Adding taxonomy to the hard
curve/scenario fingerprint (rejected - materialised grouped reports need a
separate `activity_reporting_fingerprint`, while fit and curve identity must
remain unchanged for descriptive edits).
**Impact:** `core.activities.ActivityDefinition`, explicit legacy migration,
`activity_reporting_fingerprint`, Media Mapping UI, display labels, project
round-trip coverage, and `REQ-ACTIVITY-001`. No model equations, graph
structure, pooling configuration, attribution aggregation or mixed-frequency
behaviour changed. Real UK end-to-end data validation: DEFERRED pending
source-data availability.
**Owner:** Platform engineering / Data Science.
**Status:** Accepted; implementation in Work Package 1.

## Governed activity identity before model structure (Work Package 2)

**Date:** 2026-08-13
**Decision:** Make Activity Mapping the workflow step before Model Structure.
Model Structure selects governed `ActivityDefinition` rows and resolves each
selected `market + activity_id` to its explicit `model_input_column`; the
engine-compatible `ModelSpec.channels` field remains a physical model-input
column adapter for existing model code and saved projects. The structure
summary reports governed activities, physical model-input columns, and
reporting channels separately.
**Reason:** A raw numeric-column heuristic cannot distinguish media from KPI,
control, outcome, or other numeric variables, and `ActivityDefinition.channel`
is a reporting roll-up that may be shared by multiple activities. Activity
identity must therefore be governed before model scope is selected, without a
second registry or a risky rename of all model internals.
**Alternatives considered:** Keeping the numeric-column media multiselect as
the official workflow (rejected - it silently classified arbitrary numeric
columns); renaming `ModelSpec.channels` throughout the engine (rejected -
unnecessarily broad compatibility risk); automatically creating new activity
rows from every numeric column (rejected - it would turn a suggestion into an
authoritative business classification). Legacy projects instead receive an
explicit review-required compatibility adapter from their saved
`ModelSpec.channels` or legacy pathway metadata.
**Impact:** `core.activities` now exposes reusable activity identity/model-input
resolvers and the explicit legacy adapter; Activity Mapping can run after
prepared data and before Model Structure; workflow state and navigation reflect
the corrected order; Model Structure no longer uses naming heuristics to select
media. No model equations or causal graph semantics changed. Real UK
end-to-end data validation: DEFERRED pending source-data availability.
**Owner:** Platform engineering / Data Science.
**Status:** Accepted; implementation in Work Package 2.

## Causal graph and pathway identity follow governed activities (Work Package 3)

**Date:** 2026-08-13
**Decision:** Seed causal graphs from governed `ActivityDefinition` rows in
model scope, using the stable scoped node key `activity:{market}:{activity_id}`.
Graph node metadata may carry business-readable labels and taxonomy for display,
but the Activity Mapping registry remains authoritative for funnel stage and
the physical model-input predictor. `MediaOutcomePathway` records now carry
`activity_id` and explicit `activity_market` for new rows while retaining the
legacy physical `channel` field as the engine compatibility view.

**Reason:** A reporting channel can contain several distinct activities, such
as multiple Paid Social activities with different funnel stages and fitted
predictors. Seeding and compiling from free-form channel strings would merge
those activities and make the causal graph ambiguous. The graph must preserve
outcomes and governed Search objects as separate node types while resolving
activity nodes to predictors through an explicit registry boundary.

**Alternatives considered:** Using `ActivityDefinition.channel` as the graph
node ID (rejected - it is a reporting family and is intentionally shareable);
using funnel-stage metadata as causal structure (rejected - taxonomy is
descriptive and changing it must not add, remove, or reverse graph edges);
guessing a legacy pathway's activity from a name or first matching row
(rejected - zero and multiple candidates remain review-required); renaming
the engine's physical `ModelSpec.channels` contract (rejected - the stable
adapter preserves saved projects and avoids a mathematical change).

**Impact:** Added scoped activity-node identity and model-scope resolvers,
activity-aware graph compilation and previews, explicit pathway identity and
legacy migration/quarantine helpers, graph/pathway UI labels, and persisted
round-trip coverage. Legacy graph node IDs and pathway predictor fields remain
compatible; ambiguous activity migration fails closed. No model equations,
funnel inference, or layout fingerprint semantics changed. Business question:
which governed activity intervention is connected to which outcome? Estimand:
the existing graph-selected direct/cross-product pathway cell on the outcome
scale. Output scale/units: physical fitted model-input columns, outcome IDs,
and governed activity IDs; no new numeric response is introduced. Upstream
modelling references: none consulted because this package changes identity and
compilation metadata only, not PyMC/PyMC Marketing model APIs. Real UK
end-to-end data validation: DEFERRED pending source-data availability.

**Owner:** Platform engineering / Data Science.
**Status:** Accepted; implementation in Work Package 3.

## Governed activity roll-ups in attribution and reporting (Work Package 4)

**Date:** 2026-08-13
**Decision:** Add a framework-independent reporting enrichment boundary that
joins contribution, curve, and economic rows to the governed activity
dictionary, then supports deterministic roll-ups by activity, reporting
channel, platform, campaign type, marketing objective, message type, funnel
stage, product, market, outcome, segment, and explicit pathway/effect type.
Posterior rows are aggregated by `posterior_draw` before summary statistics.
Direct, mediated, halo, and total effects remain separate; funnel stage is
never used to infer a causal effect.

**Reason:** The activity taxonomy is analytically useful only if business
views can move from funnel to channel/platform to activity without merging
distinct Meta or CRM activities or relabelling a descriptive funnel bucket as
mediation. Unclassified activities must remain visible and mark a funnel
decomposition incomplete rather than being dropped.

**Alternatives considered:** Grouping raw model-input columns directly
(rejected - they are engine predictors, not governed business identity);
inferring mediated effects from `funnel_stage` (rejected - funnel taxonomy is
descriptive); summing posterior summaries or independently summarised
component medians (rejected - this understates or distorts uncertainty);
allocating the same component spend to direct and mediated rows (rejected -
component economics require an explicit cost allocation and channel spend is
counted once).

**Impact:** Added `core.reporting_rollups` enrichment, draw-safe aggregation,
posterior summaries, explicit Unclassified handling, and official artifact
Funnel, Channel/platform, and Activity drill-down views. Persisted official
curve artifacts already carry the activity-governance snapshot and its
fingerprint; roll-up outputs expose that same taxonomy fingerprint. No model
equations, causal edges, pathway estimands, or curve generation math changed.
Business question: how much approved response/contribution is associated with
each governed activity and its reporting groups? Estimand: the supplied
outcome-scale contribution/curve/economic row under its existing pathway and
governance definition, aggregated at draw level. Output scale/units: the
input row's declared response/value/spend units; no conversion or causal
reinterpretation is introduced. Upstream modelling references: none
consulted because this package changes reporting enrichment and aggregation,
not PyMC/PyMC Marketing model APIs. Real UK end-to-end data validation:
DEFERRED pending source-data availability.

**Owner:** Platform engineering / Data Science.
**Status:** Accepted; implementation in Work Package 4.

## Standard source-pack parsing and workbook provenance (Work Package 5)

**Date:** 2026-08-13
**Decision:** Implement the approved `REQ-DATAIN-001` source-pack boundary as
versioned logical-domain schemas. Excel workbooks are parsed sheet-by-sheet;
standard tables retain their logical identity, unknown sheets remain separate
and visible, and activity data is canonicalised into the existing model-ready
wide boundary only through explicit dictionary mappings. Workbook checksum,
schema version, sheet names, parsed table IDs, and validation diagnostics are
persisted with the source-version history.

**Reason:** The application must support multiple physical extracts under a
logical domain without merging distinct semantics or silently treating a
first sheet as the complete workbook. Activity identity, pooling metadata,
native frequency, paid/owned/earned ownership, and missingness must survive
the upload-to-model boundary without inference.

**Impact:** Added standard schemas for Outcomes, Activity and Media, Context
and External Factors, and Experiment Evidence; multi-sheet parsing and
validation; explicit generic Excel fallback; activity canonicalisation;
workbook-level provenance; Data Upload schema guidance; and UK/AU-style
fixture coverage for partial activity history, native monthly context,
events, activity ownership, and cross-market pooling identity. No frequency
conversion, causal inference, or model algebra was added. Business question:
can governed source packs be uploaded and mapped without losing physical
table identity or activity semantics? Estimand: none introduced; the output
is a model-input mapping at the declared source grain. Output scale/units:
source-native rows plus explicitly mapped model-input columns and source
provenance metadata. Upstream modelling references: none consulted because
this package changes ingestion and canonicalisation contracts, not PyMC or
PyMC Marketing model APIs. Remaining limitation: downloadable `.xlsx`
template-byte generation is not included until the required spreadsheet
artifact helper is available in the coding environment; the schema and
validator are ready for that adapter.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in Work Package 5 ingestion scope; template-byte
adapter remains environment-blocked.

## Official mixed-frequency preparation remains fail-closed (Work Package 6)

**Date:** 2026-08-13
**Decision:** No concrete frequency-conversion method is approved for official
use. Add a framework-independent official-preparation assessment that requires
an explicit governed canonical calendar, preserves native-frequency source
rows and missingness, and returns `decision_required` or
`unsupported_no_approved_method` for unresolved mixed-frequency requests.

**Reason:** `REQ-COVERAGE-001` approves the typed, variable-class-specific
frequency contract but explicitly leaves the statistical method unresolved.
The candidate survey is decision support only. An inner join, interpolation,
allocation, forward-fill, or generic Transform Pipeline fill cannot become an
implicit official method.

**Impact:** `core.frequency_alignment.assess_official_preparation` now wires
the existing calendar/alignment contract to the Model Configuration page's
separate official-preparation action. Exploratory preparation remains
available, and generic Transform Pipeline operations remain available with an
explicit exploratory label. The exact open choices by variable class are
recorded in `docs/decision_required_frequency_methods.md`. No data conversion,
model equation, or statistical method was added.

**Owner:** Data Science / Platform engineering.
**Status:** Implemented at the governance boundary; concrete method decision
and conversion executor remain open.

## Canonical native weekly official preparation (Work Package 2)

**Date:** 2026-08-14
**Decision:** Keep the existing Transform Pipeline as an exploratory utility,
and add a separate framework-independent official preparation path for inputs
already at an explicitly governed weekly cadence. The official path joins the
union of governed source keys with an outer join, preserves nulls and source
periods, rejects exploratory fill/drop operations, and requires a governed
calendar. It does not execute mixed-frequency conversion.

**Reason:** The previous official action could consume the current transformed
frame even when that frame had been created by an inner intersection. That
could silently discard a source period before coverage review. No approved
mixed-frequency method exists, so the safe implementation boundary is a
canonical native weekly path plus an explicit fail-closed gate.

**Impact:** Added `core.official_preparation` for canonical native framing and
fit-consumed capability evidence. The capability report covers included
outcomes, media/model inputs, controls, promotions, and governed Search
predictors, while Fourier/trend/deterministic pipeline terms remain separate
from source coverage. Missing or unresolved coverage blocks only when the
variable is consumed by the compiled proposal; unrelated coverage gaps remain
reviewable without blocking this fit. Official preparation and model identity
now persist calendar, alignment, capability, and canonical-frame evidence.
No interpolation, allocation, fill, missing-data likelihood, FR-MOD-015
handling, or mixed-frequency statistical method was introduced.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in WP2; concrete mixed-frequency methods and the
broader policy-backed approval gate remain open.

## Realistic source-native synthetic demo pack (Work Package 7)

**Date:** 2026-08-13
**Decision:** Keep the fast rectangular weekly fixture for quick exploration,
and add a separate deterministic source-native fixture for ingestion-contract
and end-to-end source-pack testing. The realistic fixture retains tidy activity
rows, dictionaries, outcomes, native weekly/monthly context, and irregular
events as separate tables until an explicit canonicalisation boundary.

**Reason:** The application must demonstrate the approved data-input contract
without implying that all real data arrives as one rectangular weekly-wide
media/control table. The fixture exposes multiple activities within a
channel, multiple CRM purposes, cross-market identity, market-specific absence,
ragged history, mixed native frequency, and irregular events.

**Impact:** Added the deterministic `realistic-source-pack-v1` loader and a
Data Sources action alongside the existing quick demo. Added contract tests
for reproducibility, source-native missingness, identity/pooling metadata,
domain canonicalisation, native frequencies, and irregular events. No
frequency conversion, zero-fill, causal inference, model equation, or
persistence-schema change was introduced. Business question: can a realistic
synthetic source pack exercise the approved ingestion boundary without losing
source grain or semantics? Estimand: none introduced; outputs remain source
rows and explicitly mapped model-input columns. Output scale/units: source
native activity values (`spend`/`sends`), outcome counts, context indices, and
event dates. Upstream modelling references: none consulted because this
package changes demo/source-contract fixtures and UI loading only, not PyMC or
PyMC Marketing model APIs. Remaining limitation: the realistic fixture is
synthetic and does not represent Ancestry calibration or official business
definitions.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in Work Package 7.

## Source-to-preparation workflow boundary (UX/UI coherence Phase 1)

**Date:** 2026-08-13
**Decision:** Keep the quick rectangular fixture and source-native packs as
distinct analyst journeys. The Data Sources page now reports uploaded
file/workbook, data-category, and table counts separately. Prepare Data only
offers its rectangular join controls for rectangular inputs; recognised
source-native layouts stop at an explicit preparation boundary.

**Reason:** Dictionaries, irregular events, and native-frequency context are
not generic join inputs. The current application has no approved end-to-end
method for combining weekly activity/outcomes with monthly context for
official modelling. Presenting the generic all-table join as the next step
would teach an invalid data model and invite silent flattening or filling.

**Impact:** Added a framework-independent source inventory/layout helper,
source-aware Data Sources inventory, source-native Prepare Data boundary,
human-readable join-health and transformation summaries, and updated workflow
copy. Rectangular join behaviour, persistence keys, source table storage,
canonicalisation, and mixed-frequency fail-closed governance are unchanged.
No analytical or governance behaviour was changed; no values are converted,
interpolated, allocated, or filled by this package. Business question: can a
new analyst understand which loaded inputs are files, categories, and tables,
and whether the current preparation route is safe? Estimand: none introduced.
Output scale/units: presentation counts, source-table rows, and existing join
diagnostics in their stored units. Upstream modelling references: none
consulted because this is a presentation/workflow package and does not change
PyMC or PyMC Marketing model APIs. Remaining limitation: full source-native
mixed-frequency preparation and downloadable workbook template bytes remain
separate future packages subject to their existing decision/tooling boundaries.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 1.

## Activity Mapping workspace hierarchy (UX/UI coherence Phase 2)

**Date:** 2026-08-13
**Decision:** Present governed activities as a compact comparison overview
with one selected-activity detail form. The overview contains market,
activity, reporting channel, platform, funnel stage, media input, planning
eligibility, and review status. The detail form keeps the complete
ActivityDefinition contract available in grouped Identity and reporting,
Model and planning, Evidence and review, and Technical and provenance sections.

**Reason:** The prior default editor exposed the full governance record as a
wide multi-purpose grid. That made the first interaction feel like database
administration and made the important identity and model-input choices harder
to compare. The underlying record remains fully governed and auditable.

**Impact:** Added native Streamlit overview, selected-activity actions, grouped
detail editing, add/remove confirmation, and concise activity labels. Search
objects and physical delivery/cost mappings remain separate. Existing
ActivityDefinition validation, persistence, invalidation, multiple activities
per reporting channel, market identity, and pooling-group semantics are reused
unchanged. No analytical or governance behaviour was changed. Business
question: can an analyst identify and compare activities quickly while keeping
all governed fields accessible? Estimand: none introduced. Output scale/units:
governed activity metadata and existing source/model-input identifiers in their
stored units. Upstream modelling references: none consulted because this is a
presentation/orchestration package and does not change PyMC or PyMC Marketing
model APIs. Remaining limitation: the Search-object governance editor and
physical delivery/cost sections remain separate work surfaces rather than a
single master-detail inspector.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 2.

## Model Structure and Causal Graph workflow hierarchy (UX/UI coherence Phase 3)

**Date:** 2026-08-13
**Decision:** Keep the Model Structure scope summary readable as two compact
three-metric rows, show activity choices as activity · market · reporting
channel, and keep implementation names out of routine activity guidance.
Present Causal Graph node roles, edge roles, and lag choices through shared
human-readable labels, a compact text role legend, and a status badge. Route
the Causal Graph next step to Market Context before Model Setup.

**Reason:** Recent governed activity and graph capabilities made both pages
technically precise but harder to scan. Six equal metrics were cramped at
narrow supported widths, activity selectors prioritised source syntax, graph
canvas labels exposed enum values, and the next-step copy skipped a registered
workflow page.

**Impact:** Presentation labels, responsive grouping, status rendering, graph
role/lag display, and workflow guidance changed. Stored role keys, graph
validation, graph compilation, structure persistence, and the registered page
order remain unchanged. No analytical or governance behaviour changed.
Business question: can an analyst understand model scope and causal structure,
then follow the registered workflow without learning repository terminology?
Estimand: none introduced. Output scale/units: presentation-only scope counts,
activity identities, graph roles, edge relationships, and lag descriptions;
underlying model-input units and graph semantics are unchanged. Upstream
modelling references: none consulted because this is a presentation/workflow
package and does not change PyMC or PyMC Marketing model APIs. Remaining
limitation: final responsive and browser verification depends on the CI browser
journey because an interactive browser was unavailable in the local session.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 3.

## Official-versus-exploratory Model Setup readiness (UX/UI coherence Phase 4)

**Date:** 2026-08-13
**Decision:** Keep the existing fail-closed official frequency-preparation
boundary unchanged, but present its result as a readable readiness panel.
Official preparation is the dominant action and shows its status, conversion
need, reason, decisions required, and safe next action. Exploratory frame
preparation remains available as a secondary investigation route and is
explicitly labelled as not satisfying official preparation.

**Reason:** The raw assessor status `unsupported_no_approved_method` was
accurate but not suitable as routine analyst-facing copy. The previous primary
exploratory button also made an exploratory frame look like the official
workflow had completed. A model frame can be useful for investigation while
the official frequency decision remains unresolved, so those states must be
visible without inventing a conversion method or changing the analytical gate.

**Impact:** Added human-readable official-preparation status and conversion
summary, kept the raw assessor key in collapsed Technical details, made the
official action primary, renamed and de-emphasised exploratory preparation,
and marked Model Setup as exploratory rather than complete when only an
exploratory frame exists. Data Coverage and Home now explain when a page is
optional for exploratory continuation but still required for official
preparation, and Home surfaces an existing official blocker. No analytical,
frequency-alignment, governance, persistence, or model-fitting behaviour was
changed. Business question: can an analyst safely tell whether the current
frame is official-ready or exploratory-only, and what must be resolved next?
Estimand: none introduced. Output scale/units: presentation labels and
workflow readiness states over existing source-native data and model-frame
units. Upstream modelling references: none consulted because this package
changes presentation/workflow state only and does not change PyMC or PyMC
Marketing model APIs. Remaining limitation: the conversion executor remains a
separate governed capability and is not invented by this phase.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 4.

## Diagnostics and model-comparison language (UX/UI coherence Phase 5)

**Date:** 2026-08-13
**Decision:** Lead Diagnostics drift messaging with the analyst consequence:
outcome definitions have changed since the model was fitted. Show the affected
outcomes with human-readable labels and what action is needed, while retaining
exact outcome IDs and status keys in collapsed Technical details. Describe
Model Comparison candidates by their response structure before any internal
aliasing.

**Reason:** The previous drift message exposed repository vocabulary and an
internal catalogue metaphor before explaining what the analyst should do.
The comparison introduction likewise led with A/B/C aliases even though the
decision depends on shared, independent, or partially pooled response
structures.

**Impact:** Updated the shared drift component used across analytical pages,
Diagnostics model labels, Model Comparison guidance, and their tests. The
existing changed/removed blocking statuses, independent evidence dimensions,
stored identifiers, and approval/readiness behaviour are unchanged. Business
question: have outcome definitions changed since this model was fitted, what
does that mean for current evidence, and which model structure is being
compared? Estimand: none introduced. Output scale/units: presentation copy and
human-readable outcome-definition change summaries; underlying outcome values
and diagnostic units are unchanged. Upstream modelling references: none
consulted because this package changes presentation only and does not change
PyMC or PyMC Marketing model APIs. Remaining limitation: exact model-run and
outcome identifiers remain technical fields for audit and recovery.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 5.

## Results language and reporting views (UX/UI coherence Phase 6)

**Date:** 2026-08-13
**Decision:** Present Results as fitted contribution evidence, exploratory
response curves, official response curves, and saved parameter snapshots.
Reporting roll-ups are labelled by the analyst question they answer: funnel
group, channel and platform, or activity. Funnel group remains a reporting
dimension rather than a causal or mediation label, and direct, mediated,
cross-product, halo, residual-interaction, and total effects remain separate.
Stable outcome IDs, roll-up status keys, and saved-curve identifiers remain
available in collapsed Technical details.

**Reason:** The Results page had accumulated storage-oriented language such as
artifact store, legacy viewers, and curve-bank terminology. The reporting tabs
also exposed schema dimensions and technical roll-up flags before explaining
what the view was for. The revised hierarchy should help an analyst choose the
right level of reporting without weakening the causal and governance
distinctions.

**Impact:** Updated Results headings, captions, contribution tables, waterfall
selectors, official response-curve summaries, reporting-view tabs, and saved
parameter history labels. Visible tables now use human-readable outcome and
effect labels; technical identifiers and aggregation metadata are disclosed
secondarily. Posterior-draw aggregation, response values, curve economics,
effect taxonomy, authorization gates, persistence keys, and approval semantics
are unchanged. No analytical or governance behaviour changed. Business
question: can an analyst understand what each Results view answers, retain
context while moving from funnel to channel/platform to activity, and tell
exploratory evidence from official response curves? Estimand: none introduced.
Output scale/units: existing outcome-scale incremental response, spend/cost
measures, posterior uncertainty summaries, and model-input or monetary curve
axes; only their presentation labels and grouping context changed. Upstream
modelling references: none consulted because this package changes presentation
only and does not change PyMC or PyMC Marketing model APIs. Remaining
limitation: browser screenshot verification uses the repository's CI browser
journey because an interactive browser was unavailable in the local session.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 6.

## Response-curve annotation contrast (UX/UI coherence Phase 7)

**Date:** 2026-08-13
**Decision:** Use the existing light analytical surface for the fixed response-
curve annotation box, with the existing dark primary text token and subtle
border. Preserve the annotation content, position, chart values, uncertainty,
observed-support band, current-point marker, and axis semantics.

**Reason:** The previous annotation used a dark semi-transparent background
with dark theme text, which reduced readability in the application's light
analytical theme. The shared chart builder is the correct presentation boundary
for all exploratory and official annotated response curves.

**Impact:** Changed only Plotly annotation styling and added a contrast
regression test. No analytical or governance behaviour changed. Business
question: can an analyst read evidence, support, extrapolation, and economics
annotations without losing the curve context? Estimand: none introduced.
Output scale/units: unchanged response values, uncertainty intervals, model-
input or monetary axes, and existing annotation text. Upstream modelling
references: none consulted because this package changes chart presentation only
and does not change PyMC or PyMC Marketing model APIs. Remaining limitation:
visual screenshot review through the connected in-app browser was unavailable;
the repository's synthetic-data browser journey and figure-level contrast test
provide the available visual regression evidence.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 7.

## Planning Curve language and progressive disclosure (UX/UI coherence Phase 8)

**Date:** 2026-08-13
**Decision:** Centre the official-curve workflow on the analyst-facing
Planning Curve. Use readable labels for downstream permissions, keep the
stored permission keys and governance checks unchanged, and make the normal
cost-mapping view show only market, activity/channel, method, currency,
effective dates, and approval state. Keep mapping IDs, knot arrays,
extrapolation, source, and audit fields in a secondary advanced disclosure.

**Reason:** The page exposed implementation nouns such as artifact,
curve_publication, authorization state, and requested-use enum keys before
answering whether the Planning Curve was ready and where it could be used.
The full cost-mapping schema was also visually dense for the normal path.

**Impact:** Updated Planning Curves headings, guidance, readiness language,
permission labels, success/error copy, curve-axis labels, and status tables.
The compact and advanced cost-mapping editors merge back into the same durable
mapping schema, so no mapping field is discarded. Monetary curves still require
approved effective mappings, currency/FX evidence, and governed support; model-
input curves still suppress monetary CPA/ROI. No analytical, mathematical,
approval, authorization, persistence, or stored-key behaviour changed.
Business question: is the approved fit ready to become a Planning Curve, what
does it represent, and which downstream uses are currently permitted?
Estimand: none introduced. Output scale/units: unchanged model-input or
monetary curve axes, outcome-scale response, posterior intervals, and monetary
economics where valid. Upstream modelling references: none consulted because
this package changes presentation only and does not change PyMC or PyMC
Marketing model APIs. Remaining limitation: interactive browser screenshot
review uses the repository's synthetic-data browser journey because the local
connected browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 8.

## Scenario Planner limitation hierarchy (UX/UI coherence Phase 9)

**Date:** 2026-08-13
**Decision:** Keep the steady-state monthly limitation as the prominent first-
viewport decision cue, but shorten it to the practical consequence for an
analyst. Keep the full boundary—no sequential week-over-week carry-in
simulation, no capacity-constrained delivery model, and no Chronos-2 or other
external forecast path—in the existing collapsed Technical details disclosure.
Retain the allocation desk, editable/calculated/proposed/saved state flow,
official-versus-exploratory governance, and unconstrained benchmark warning
unchanged.

**Reason:** The existing limitation was accurate but warning-heavy at the top
of the page. The first viewport should answer the main modelling-method
question quickly, while the technical boundary remains available before a
planning decision is made.

**Impact:** Updated only the Scenario Planner's top limitation copy and its
AppTest expectation. No scenario calculations, counterfactual policy,
capacity/cap semantics, approval/readiness gate, optimisation eligibility,
currency/value mapping, persistence, or saved-state behaviour changed. The
existing model-approval/readiness gate remains the authoritative prerequisite
for governed planning; no duplicate or weaker readiness signal was added.
Business question: what does this planner evaluate, and which important
planning behaviours are outside its current method? Estimand: none
introduced. Output scale/units: unchanged scenario outcome, value, spend, and
uncertainty outputs. Upstream modelling references: none consulted because
this package changes presentation only and does not change PyMC or PyMC
Marketing model APIs. Remaining limitation: interactive browser screenshot
review uses the repository's synthetic-data browser journey because the local
connected browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 9.

## Export & Recovery language and bundle contents (UX/UI coherence Phase 10)

**Date:** 2026-08-13
**Decision:** Keep the durable project bundle as the primary recovery object,
with Excel and report outputs secondary and read-only. Humanise the routine
labels for source files/tables, preparation steps, activity taxonomy, search
definitions, coverage/frequency review history, exploratory curve snapshots,
and governed Planning Curves. Keep the manifest-driven included/not-included
checklist and collapsed Technical details disclosure as the places for bundle
contents and storage/provenance detail.

**Reason:** Export & Recovery was already structurally focused, but several
routine captions still described storage implementation—legacy curve bank,
logical-domain definitions, matrix versions, and official curve artifacts.
The recovery page should tell an analyst what can be recovered and what the
current project contains without turning into a second analytical dashboard.

**Impact:** Updated presentation labels and restore/build confirmation copy,
and surfaced the saved activity-taxonomy count in the existing project
snapshot. The manifest keys, checkpoint values, export/import calls, source
and coverage history, activity definitions, curve stores, resumability audit,
official verification, and transactional restoration semantics are unchanged.
Business question: what is the durable recovery object, what evidence and
preparation state does it contain, and can it be restored safely? Estimand:
none introduced. Output scale/units: unchanged project metadata, checkpoint,
bundle contents, and resumability status. Upstream modelling references: none
consulted because this package changes presentation only and does not change
PyMC or PyMC Marketing model APIs. Remaining limitation: interactive browser
screenshot review uses the repository's synthetic-data browser journey because
the local connected browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 10.

## Restrained semantic status icons (UX/UI coherence Phase 11)

**Date:** 2026-08-13
**Decision:** Keep text as the authoritative status signal and reduce the
shared badge system to six repeated semantic cues: completion, information,
attention, blocked/failed, progress, and neutral. Keep sidebar icons only for
attention states, using one warning cue for review/stale/unavailable and one
block cue for blocked. Route the Diagnostics readiness and funnel-coherence
headings through the shared status presentation.

**Reason:** The existing badges were accessible because icons were paired with
text, but the larger icon vocabulary made similar states look unrelated and
required unnecessary memorisation. A restrained repeated vocabulary preserves
non-colour meaning while making the interface calmer and more predictable.

**Impact:** Presentation-only changes to shared status icons, sidebar attention
icons, and two Diagnostics headings. No lifecycle values, readiness decisions,
diagnostic calculations, governance gates, or analytical outputs changed.
Business question: what does each status mean and what needs attention?
Estimand: none introduced. Output scale/units: unchanged. Upstream modelling
references: none consulted because this package changes presentation only and
does not change PyMC or PyMC Marketing model APIs. Remaining limitation:
interactive browser screenshot review uses the repository's synthetic-data
browser journey because the local connected browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 11.

## Analyst-readable typography (UX/UI coherence Phase 12)

**Date:** 2026-08-13
**Decision:** Raise the shared shell's smallest supporting text to a readable
common scale, including navigation group labels, context labels, the sidebar
footnote, workbench-note labels, captions, and metric labels. Preserve strong
page and section hierarchy, allow status/context/metric text to wrap, and add
responsive sidebar/context spacing at narrower target widths. Important copy
must wrap before it is reduced to a tiny label.

**Reason:** Several repeated shell labels were between roughly 0.66rem and
0.72rem. That density made workflow context and analyst-facing qualifiers
harder to scan, especially at the 1024px target width. A shared type scale
improves readability without adding a brand font or changing page content.

**Impact:** Presentation-only CSS/token changes and shell CSS tests. No page
content, metrics, analytical calculations, workflow state, governance rules,
or persistence behaviour changed. Business question: can an analyst read the
workflow context, metric labels, captions, and technical qualifiers at the
supported widths? Estimand: none introduced. Output scale/units: unchanged.
Upstream modelling references: none consulted because this package changes
presentation only and does not change PyMC or PyMC Marketing model APIs.
Remaining limitation: interactive browser screenshot review uses the
repository's synthetic-data browser journey because the local connected
browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 12.

## Semantic highlight roles (UX/UI coherence Phase 13)

**Date:** 2026-08-13
**Decision:** Centralise shared highlight roles for selected interaction
surfaces, informational surfaces, caution surfaces, and blocking surfaces.
Use the interaction/selection tone only for selection and action cues; keep
information, caution, and negative surfaces tied to their semantic status
colours. Reuse the same maps for sidebar selection, shared panels, and native
info alerts.

**Reason:** The existing rendered colours were already appropriate, but their
use was repeated across shared CSS and theme overrides. Central role maps make
the reason for each highlight explicit and reduce the risk that an accent or
context colour is used as an unexplained warning or decorative emphasis.

**Impact:** Presentation-only token/CSS consolidation and tests. Rendered
colours are unchanged. No analytical calculations, workflow states,
governance rules, persistence, or page content changed. Business question:
does each highlighted surface communicate interaction, information, caution,
or a blocker—and does a blocker remain visually louder than context? Estimand:
none introduced. Output scale/units: unchanged. Upstream modelling
references: none consulted because this package changes presentation only and
does not change PyMC or PyMC Marketing model APIs. Remaining limitation:
interactive browser screenshot review uses the repository's synthetic-data
browser journey because the local connected browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 13.

## Concise empty and blocked states (UX/UI coherence Phase 14)

**Date:** 2026-08-13
**Decision:** Keep the primary empty/blocked message as the single prominent
explanation. Render optional purpose, dependency, and next-action details as
supporting captions beneath it, followed by the existing safe navigation
button. Preserve the existing info-versus-error severity and target workflow
route.

**Reason:** Structured empty-state details were previously bolded inside the
primary info/error surface. On prerequisite pages that made secondary context
compete with the actual blocker and increased first-viewport prose. The
analyst still sees the same explanation and action, but the hierarchy is now
message first, supporting detail second, action third.

**Impact:** Presentation-only shared-component rendering and AppTest updates.
No workflow routes, blocking conditions, page content, analytical
calculations, governance rules, or persistence behaviour changed. Business
question: what is unavailable, why, and what safe action should the analyst
take next? Estimand: none introduced. Output scale/units: unchanged. Upstream
modelling references: none consulted because this package changes
presentation only and does not change PyMC or PyMC Marketing model APIs.
Remaining limitation: interactive browser screenshot review uses the
repository's synthetic-data browser journey because the local connected
browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 14.

## Consequence-first drift copy (UX/UI coherence Phase 15)

**Date:** 2026-08-13
**Decision:** Make the shared drift message lead with the consequence: the
fitted model no longer matches the affected outcome definition(s). For
calculation-relevant drift, state the safe action directly—refit the model or
restore the fitted definitions before using dependent results. For
non-blocking drift, ask the analyst to review the changes before interpreting
current evidence. Keep the existing severity, drift classification, detail
table, and collapsed technical status keys unchanged.

**Reason:** The former message described a historical change first and used
"calculation-dependent results" as an abstract consequence. Analysts need to
know whether the current fit can still be used and what action restores a
safe state.

**Impact:** Presentation-only shared copy and focused component-test updates.
No drift detection, status classification, blocking gate, model identity,
approval, persistence, or analytical behavior changed. Business question:
does the current fitted model still match the outcome definitions, and what
must the analyst do if it does not? Estimand: none introduced. Output
scale/units: unchanged. Upstream modelling references: none consulted because
this package changes presentation only and does not change PyMC or PyMC
Marketing model APIs. Remaining limitation: interactive browser screenshot
review uses the repository's synthetic-data browser journey because the local
connected browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 15.

## Recognisable coverage-fabric marks (UX/UI coherence Phase 16)

**Date:** 2026-08-14
**Decision:** Replace the Coverage fabric's cryptic single-letter marks for
covered, modelled, suppressed, and unavailable-source states with familiar
status notation: check, approximate, function, dash, suppression, and empty
set marks as applicable. Retain the existing state labels, hover details,
legend, colours, and one mark per segment so colour is never the sole state
signal.

**Reason:** The previous `M`, `S`, and `U` marks made the fabric a code that
analysts had to memorise. The brief's coverage-glyph review calls for symbols
that improve recognition without changing the governed missingness vocabulary
or implying a new state.

**Impact:** Presentation-only chart marks and coverage-chart test updates.
No coverage classification, treatment approval, readiness, analytical
calculation, governance rule, or persistence behaviour changed. Business
question: can an analyst scan the coverage fabric and recognise the status of
a segment without relying on colour or memorised single-letter codes?
Estimand: none introduced. Output scale/units: unchanged. Upstream modelling
references: none consulted because this package changes presentation only and
does not change PyMC or PyMC Marketing model APIs. Remaining limitation:
interactive browser screenshot review uses the repository's synthetic-data
browser journey because the local connected browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 16.

## Question-led reporting roll-up tabs (UX/UI coherence Phase 17)

**Date:** 2026-08-14
**Decision:** Name the official reporting roll-up tabs by the analyst's
question: `Where in the funnel?`, `Which channel or supplier?`, and `Which
activity?`. Keep the existing reporting dimensions, table columns, posterior
aggregation, Unclassified explanation, and separate direct, mediated, halo,
and total effect components unchanged.

**Reason:** The reporting views added in PR #196 were already structurally
sound and explicitly distinguished reporting groupings from causal pathways,
but their tab labels still described schema dimensions first. Question-led
labels make the intended decision context visible before the table is read.

**Impact:** Presentation-only tab labels and AppTest expectations. No
reporting aggregation, effect taxonomy, outcome definition, governance rule,
analytical calculation, or persistence behaviour changed. Business question:
which reporting view should an analyst use to understand where response is,
which channel or supplier carries it, or which activity explains it?
Estimand: unchanged; the existing posterior-draw-aggregated reporting
summaries remain the estimand. Output scale/units: unchanged from the
governed artifact, including outcome counts, model-input units, and reporting
currency where present. Upstream modelling references: none consulted because
this package changes presentation only and does not change PyMC or PyMC
Marketing model APIs. Remaining limitation: interactive browser screenshot
review uses the repository's synthetic-data browser journey because the local
connected browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 17.

## Human outcome labels in routine fit and curve controls (UX/UI coherence Phase 18)

**Date:** 2026-08-14
**Decision:** Show approved outcome product, segment, metric, and definition
version in the Fit Model proposal and Planning Curve outcome selector. Keep
stable outcome IDs as the internal selector values and governance keys; do
not change outcome resolution, approval filtering, model identity, or saved
curve metadata.

**Reason:** The page-to-page terminology sweep found raw outcome IDs in two
routine controls even though the outcome registry already supplied the human
definition. Analysts should recognise the selected measure consistently
across fitting and Planning Curve creation without learning repository keys.

**Impact:** Presentation-only outcome labels, selector formatting, and focused
AppTest expectations. No outcome definition, maturity rule, approval use,
model calculation, curve calculation, persistence, or governance behaviour
changed. Business question: which approved outcome definition is being fitted
or used to create a Planning Curve? Estimand: unchanged; the selected
registry outcome and its existing definition remain the estimand. Output
scale/units: unchanged and still determined by the selected outcome and
model-input/cost mapping. Upstream modelling references: none consulted
because this package changes presentation only and does not change PyMC or
PyMC Marketing model APIs. Remaining limitation: interactive browser
screenshot review uses the repository's synthetic-data browser journey
because the local connected browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 18.

## Human coverage-state explanations (UX/UI coherence Phase 19)

**Date:** 2026-08-14
**Decision:** Replace raw coverage state keys in routine Coverage & Gaps
explanations with human labels: expected data missing, source unavailable,
not applicable, suppressed, estimated, modelled, observed zero, and unknown.
Rename the variable selector to `Variables to review` and humanise the
summary table's displayed gap-state values. Keep the stored enum keys, editor
round-trip, state filtering, classification validation, and treatment gates
unchanged.

**Reason:** The Coverage & Gaps page still exposed implementation values such
as `missing_expected` and `unavailable_source` in help text. These keys are
useful to the persistence and validation contract but create an unnecessary
code to learn in routine analyst guidance.

**Impact:** Presentation-only coverage copy and display-value changes, plus
focused AppTest coverage. No coverage classification, treatment approval,
official-readiness rule, persistence schema, analytical calculation, or
filter semantics changed. Business question: can an analyst understand what
each coverage gap means and what needs review without learning internal state
keys? Estimand: none introduced. Output scale/units: unchanged. Upstream
references: none consulted because this package changes presentation only and
does not change PyMC or PyMC Marketing model APIs. Remaining limitation:
interactive browser screenshot review uses the repository's synthetic-data
browser journey because the local connected browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 19.

## Human fit-support language in Model Config (UX/UI coherence Phase 20)

**Date:** 2026-08-14
**Decision:** Rename the routine Model Config coverage section to `Data
coverage & fit support`, describe the complete market × channel requirement as
today's supported fit scope, and use the same wording in the Diagnostics
approval-context message. Keep the governed coverage matrix, capability check,
exploratory availability, stale-fingerprint handling, issue report, and
official-readiness semantics unchanged.

**Reason:** The previous copy exposed implementation-oriented terms such as
`engine capability` and `rectangular capability` in a routine configuration
review. Analysts need to understand the actionable question—whether the
selected market/channel configuration is supported by the current fit path—
without losing the requirement that every requested cell be genuinely
observed.

**Impact:** Presentation-only section labels, explanatory copy, and focused
AppTest expectations. No coverage classification, capability calculation,
exploratory or official preparation gate, approval policy evaluation,
persistence, model calculation, or governance rule changed. Business question:
is the selected market/channel configuration supported for the current fit
path, and if not, which governed coverage cells still need resolution?
Estimand: none introduced. Output scale/units: unchanged. Upstream modelling
references: none consulted because this package changes presentation only and
does not change PyMC or PyMC Marketing model APIs. Remaining limitation:
interactive browser screenshot review uses the repository's synthetic-data
browser journey because the local connected browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 20.

## Human pathway and graph detail labels (UX/UI coherence Phase 21)

**Date:** 2026-08-14
**Decision:** Keep stored activity, model-input, outcome, pathway, node, and
edge identifiers unchanged while presenting routine Model Structure pathway
choices and Causal Graph edge context with readable labels. Rename the pathway
editor's `Physical model input` display to `Mapped model input`, explain that
the media input comes from Activity Mapping, and describe the model-plan
preview as a structural support check rather than an engine-capability
message.

**Reason:** The workflow already separated reporting channels, mapped model
inputs, and causal objects correctly, but a few routine displays still exposed
source-style identifiers or implementation language. Analysts should be able
to choose and inspect a pathway or graph edge without learning repository keys;
the exact keys remain available to the persistence and validation contracts.

**Impact:** Presentation-only pathway row labels, one column label/help text,
one graph inspector caption, model-plan preview copy, and focused AppTest
expectations. No pathway role, graph role, model-input mapping, validation,
compilation, persistence, approval, or governance behaviour changed. Business
question: can an analyst identify the activity, market, outcome, pathway type,
and graph relationship from the routine controls without interpreting raw
storage keys? Estimand: none introduced. Output scale/units: unchanged;
existing model-input units and outcome definitions remain authoritative.
Upstream modelling references: none consulted because this package changes
presentation only and does not change PyMC or PyMC Marketing model APIs.
Remaining limitation: interactive browser screenshot review uses the
repository's deterministic synthetic-data browser journey because the local
connected browser was unavailable.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 21.

## Shorter Model Structure activity choices (UX/UI coherence Phase 22)

**Date:** 2026-08-14
**Decision:** Show governed activity selectors as `Activity (Market)` and keep
the reporting channel out of the primary choice label.

**Reason:** The selector is an identity-and-scope choice, while reporting
channel is a separate roll-up. The shorter label is easier to scan without
changing the stored activity key or mapped model input.

**Impact:** Both the governed-activity and DNA-targeted selectors retain the
same stable `market::activity_id` values and downstream resolution. The
reporting channel remains available in Activity Mapping and reports. Business
question: which governed activities, in which markets, should this model
include? Estimand: none introduced. Output scale/units: unchanged.
Upstream modelling references: none consulted because this package changes
presentation only and does not change PyMC or PyMC Marketing model APIs.
Remaining limitation: Activity Mapping remains the source of fuller reporting,
planning, evidence, and provenance detail.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 22.

## Humanise compatibility-pathway copy (UX/UI coherence Phase 23)

**Date:** 2026-08-14
**Decision:** Describe pre-Activity-Mapping and reconstructed pathway states in
plain analyst language in Model Structure. Keep migration controls and saved
compatibility values unchanged, but remove routine `legacy` labels and raw
stored-field names from visible explanatory copy.

**Reason:** Compatibility support is necessary for resumability, but routine
implementation-history wording makes the normal workflow feel like an internal
migration tool. The page should explain what is available, what requires review,
and why refitting is required.

**Impact:** Presentation-only changes to compatibility notices, review warnings,
the inferred-source-product note, and the post-save confirmation. No migration,
pathway reconstruction, invalidation, approval, persistence, or governance
semantics changed. Business question: what should an analyst review before
using a saved older pathway configuration again? Estimand: none introduced.
Output scale/units: unchanged. Upstream modelling references: none consulted;
no modelling API or dependency changed.
Remaining limitation: the compatibility review remains required before headline
reporting or planning, and the exact stored migration fields remain available to
the persistence and validation contracts.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 23.

## Keep causal-plan identifiers in Technical details (UX/UI coherence Phase 24)

**Date:** 2026-08-14
**Decision:** Make the Causal Graph model-plan preview lead with a compact
summary of outcome nodes, model inputs, and structural links. Keep exact
identifier lists, pathway-mask rows, and lag structure in a collapsed
`Technical details · compilation plan` section.

**Reason:** The model plan is useful for understanding whether the graph is
structurally complete, but raw compilation identifiers are implementation
detail for routine workflow use. Progressive disclosure preserves auditability
without making the main graph page require repository-key knowledge.

**Impact:** Presentation-only change. The same `GraphCompilationPlan` values
are generated and remain available unchanged in the technical section; graph
validation, readiness, approval, compilation, persistence, and governance
semantics are unchanged. Business question: does the current graph contain the
expected outcomes, inputs, and structural relationships? Estimand: none
introduced. Output scale/units: unchanged. Upstream modelling references: none
consulted; no modelling API or dependency changed.
Remaining limitation: the compact counts do not replace the exact technical
preview, which remains available on demand.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 24.

## Humanise Coverage review language and summary headers (UX/UI coherence Phase 25)

**Date:** 2026-08-14
**Decision:** Use `variable`/`variable type` language in the routine Coverage
& Gaps review and replace raw summary-table field names with analyst-facing
headers. Present the unresolved boolean as `Official use: Review/Ready` in
the display table only.

**Reason:** Coverage is a decision surface about missingness, frequency, and
treatment. Internal field names such as `native_frequency`, `gap_segments`,
and `officially_unresolved` make the review table read like a schema dump.

**Impact:** Display-only labels and table values changed; the stored
`VariableCoverageRecord`, enum keys, source/version provenance, treatment
workflow, official-use gate, and matrix persistence are unchanged. Business
question: which variables need review before official use, and what coverage
information supports that decision? Estimand: none introduced. Output
scale/units: unchanged. Upstream modelling references: none consulted; no
modelling API or dependency changed.
Remaining limitation: stable variable IDs and provenance remain available in
the table values and Technical details where needed.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 25.

## Humanise Model Structure outcome choices (UX/UI coherence Phase 26)

**Date:** 2026-08-14
**Decision:** Show product, segment, and metric descriptions in routine Model
Structure outcome selectors, funnel-link choices, pathway summaries, and the
pathway editor. Keep stable outcome IDs as the stored values used by validation,
persistence, joins, and model fingerprints. Label the exact resolved component
table as Technical details so its implementation-level fields remain available
without dominating the routine workflow.

**Reason:** Stable outcome IDs are necessary for governed identity, but labels
such as `fh_dna_crosssell` and `dna_new_kit` make ordinary model-structure
choices read like a schema-management task. Analysts need to choose the business
outcome, not decode repository keys.

**Impact:** Presentation-only changes to outcome choice labels, pathway-row
summaries, and technical disclosure wording. Empty funnel-link state is also
normalised before the existing editor reads it, so an absent optional value
renders as an empty state rather than a page exception. Stored outcome IDs,
pathway validation, graph resolution, fit scope, persistence, and governance
semantics are unchanged. Business question: which business outcome should this
pathway or funnel relationship target? Estimand: none introduced. Output
scale/units: unchanged. Upstream modelling references: none consulted; no
modelling API or dependency changed.
Remaining limitation: the governed outcome catalogue still exposes its stable
identity column for deliberate catalogue maintenance; exact resolved component
fields remain available in the Technical details disclosure.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 26.

## Carry human outcome labels into fit scope (UX/UI coherence Phase 27)

**Date:** 2026-08-14
**Decision:** Use the governed product, segment, and metric description in
Model Setup's included/excluded outcome summaries and Fit Model's direct-DNA
response summary. Keep stored outcome IDs unchanged for selection, persistence,
model fingerprints, and fitting.

**Reason:** Model Structure now lets analysts choose outcomes by their business
meaning, but the next two workflow pages still repeated internal outcome IDs.
That made the same outcome appear to change identity as the analyst moved from
model design into fit preparation.

**Impact:** Presentation-only changes to Model Setup and Fit Model summaries.
Model Setup also fills missing fields in a restored partial prior configuration
from the existing current defaults before rendering its controls; saved values
remain authoritative and no prior meaning changes. No model inputs, outcome
inclusion rules, direct-DNA response mapping, or saved state changed. Business
question: which governed outcomes will this fit include, and which DNA outcomes
receive direct response? Estimand: none introduced. Output scale/units: unchanged.
Upstream modelling references: none consulted; no modelling API or dependency
changed.
Remaining limitation: technical source columns and stable IDs remain available
through the governed configuration and technical persistence details.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 27.

## Humanise remaining Results outcome and pathway labels (UX/UI coherence Phase 28)

**Date:** 2026-08-14
**Decision:** Show the governed product, segment, metric, and definition version
when Results presents an outcome in a waterfall, reporting summary, or official
response-curve title. Replace visible pathway captions that exposed repository
function names or internal role keys with analyst-facing descriptions.

**Reason:** Results had already moved most tables and official curve headings to
business labels, but its shared helper omitted the outcome definition version,
and pathway-strength explanations still read like implementation notes. Those
leaks made routine reporting less trustworthy and could make two versions of an
outcome indistinguishable.

**Impact:** Presentation-only changes to Results labels and pathway-strength
copy, plus AppTest coverage for versioned waterfall options and the absence of
repository identifiers in routine captions. Stable outcome IDs, definition
resolution, calculations, reporting roll-ups, curve governance, persistence,
and approval semantics are unchanged. Business question: which governed
outcome and pathway evidence is being viewed? Estimand: none introduced.
Output scale/units: unchanged. Upstream modelling references: none consulted;
no modelling API or dependency changed.
Remaining limitation: exact IDs and storage/audit fields remain available in
Technical details and persisted artefacts for traceability.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 28.

## Humanise Planning Curve setup and saved-use status (UX/UI coherence Phase 29)

**Date:** 2026-08-14
**Decision:** Present Planning Curve reference-context methods, support-method
choices, model-context previews, and channel/outcome labels in analyst language.
Keep stored mode keys, outcome IDs, control keys, and governance permission
keys unchanged. Show the saved curve's use status in the routine summary and
move its durable curve ID and stored authorization keys to Technical details.

**Reason:** The Planning Curves page had human permission labels, but routine
controls still exposed values such as `recent_average`,
`specific_scenario`, and `latest_complete_week`, while derived previews and
saved status repeated implementation identifiers. The page should centre the
Planning Curve decision without weakening the governed save and authorization
chain.

**Impact:** Presentation-only changes to option labels, reference-context
preview labels, support/control labels, chart titles, saved-status disclosure,
and the readable default curve reference. The underlying context mode,
support method, artifact ID, outcome ID, cost mapping, curve generation,
approval, authorization, persistence, and monetary validation semantics are
unchanged. Business question: is this Planning Curve configured for the right
outcome, context, units, support, and permitted use? Estimand: none
introduced. Output scale/units: unchanged. Upstream modelling references: none
consulted; no modelling API or dependency changed.
Remaining limitation: exact identifiers and advanced cost-mapping fields
remain available in Technical details and the advanced editor.

**Owner:** Platform engineering / Data Science.
**Status:** Implemented in UX/UI coherence Phase 29.

## Governed Outcomes workbook semantics and grouping (Work Package 0)

**Date:** 2026-08-14
**Decision:** Register `REQ-DATAIN-002` as the approved authority for the
richer Outcomes source contract: wide `outcomes` data; required v2
`outcome_dictionary`; optional `outcome_completeness`; explicit Product,
Metric, Breakdown, Segment, Source column and semantic group fields; a
distinct `OutcomeGroupDefinition`; separate reconciliation and model
treatment; non-conflated DNA dimensions; and v1 compatibility as an
incomplete semantic mapping. Import may seed drafts but never approval, and
causal halo remains graph/pathway configuration.
**Reason:** The fresh implementation brief identified the source-contract
gap as unresolved while the repository already has a canonical
`OutcomeDefinition`, distinct metric registry, approval gates, logical source
domains, and graph-authoritative pathways. Recording the bridge before code
changes preserves the requirements hierarchy and prevents WP1-WP8 from
inventing a parallel outcome schema or silently inferring business meaning.
**Alternatives considered:** Treating the existing two-column v1 dictionary
as sufficient (rejected - it cannot represent Product, Metric, Breakdown,
Segment, or semantic grouping); overloading `OutcomeReconciliationGroup`
(rejected - it is diagnostic arithmetic, not semantic grouping); inferring
DNA dimensions or groups from identifiers (rejected - the brief explicitly
separates customer relationship, purchase recipient, and activation status);
changing runtime behaviour in the authority package (rejected - WP0 is
documentation and registry only).
**Impact:** New `REQ-DATAIN-002`, its requirements-index entry, and a
corrected partial-capability status for `REQ-DATAIN-001`. No `ancestry_mmm/`
runtime, schema, or persisted artefact behaviour changes.
**Owner:** Data Science / Platform engineering.
**Status:** Accepted; WP0 authority registration.

## Canonical outcome dimensions and semantic groups (Work Package 1)

**Date:** 2026-08-14
**Decision:** Extend the canonical `OutcomeDefinition` with an explicit
`segment_dimension`, defaulting legacy definitions to `unspecified` and
requiring semantic review. Add a distinct immutable `OutcomeGroupDefinition`
with explicit members, product, outcome family, segment dimension, aggregation
rule, and optional supplied total. Validate both outcome dimensions and group
membership without inferring meaning from identifiers. Include the
calculation-relevant group contract and segment dimension in fit identity and
drift metadata; exclude group labels from the fingerprint.
**Reason:** WP0 established the approved source and semantic contract. The
runtime needs one canonical representation before import, persistence, model
treatment, and reporting work can consume grouped outcomes. DNA customer
relationship, purchase recipient, and activation status remain separate
dimensions, and semantic grouping must not be conflated with diagnostic
reconciliation or causal halo edges.
**Alternatives considered:** Continue using a blank/implicit segment field
(rejected - it permits unresolved legacy semantics to look approved); infer
dimensions or groups from outcome IDs (rejected - the approved brief forbids
that); reuse `OutcomeReconciliationGroup` (rejected - it represents diagnostic
arithmetic rather than semantic model/reporting grouping); fingerprint group
labels (rejected - wording is presentation-only).
**Impact:** `core.outcomes` now provides the canonical dimension/group types,
validators, JSON-safe round trips, fingerprints, and legacy helper mappings.
`fingerprint_model_spec` accepts the group payload. No Streamlit, source-pack,
persistence, import, model-equation, or reporting behaviour is changed in this
work package. Business question: which explicitly supplied outcome members
form a governed semantic total? Estimand: none introduced; aggregation remains
an explicit sum contract over supplied outcome units. Output scale/units:
unchanged and validated for compatible sum groups. Upstream modelling
references: none consulted; no modelling API or dependency changed.
**Remaining limitation:** v2 source parsing, persistence, import seeding,
model treatment, draw-level totals, and end-to-end validation remain in WP2-WP8.
Legacy definitions are loadable but require semantic review until their
dimension is explicitly supplied.
**Owner:** Data Science / Platform engineering.
**Status:** Implemented in outcome semantics WP1.

## Outcomes source-pack v2 and legacy compatibility (Work Package 2)

**Date:** 2026-08-14
**Decision:** Add a distinct `standard-source-pack-v2` Outcomes contract with
required wide `outcomes` and governed `outcome_dictionary` sheets plus an
optional `outcome_completeness` sheet. Parse v2 dictionary rows into canonical
`OutcomeDefinition` and `OutcomeGroupDefinition` objects, validate source
columns, exact metric keys, product compatibility, group consistency, and
compatible additive units, and retain the raw dictionary in
`CanonicalSourceBundle`. Preserve v1 workbooks as loadable but incomplete
legacy mappings with no inferred product, metric, segment dimension, or group.
When a supplied total is explicitly present, derive a separate diagnostic
`OutcomeReconciliationGroup`; do not create causal edges or fit treatment.
Completeness rows bind to the current NBT definition fingerprint and version;
the parser never reconstructs NBT or creates approval.
**Reason:** The approved source contract needs a machine-readable bridge from
the provider's wide values to the canonical outcome registry while keeping
source meaning, arithmetic reconciliation, causal structure, model treatment,
and approval as separate concerns. The old v1 shape must remain loadable for
existing projects without silently turning IDs into business definitions.
**Alternatives considered:** silently upgrading v1 to v2 (rejected - missing
semantics must remain visible for review); inferring definitions from outcome
IDs (rejected - the authority brief forbids it); making `outcome_completeness`
or source fingerprints provider responsibilities (rejected - the platform
binds completeness to the current canonical definition); storing only parsed
objects and discarding the dictionary (rejected - raw source meaning and
provenance must remain inspectable).
**Impact:** `data.templates` now detects v1/v2 Outcomes workbooks, parses
canonical definitions/groups, carries completeness metadata and diagnostic
reconciliation in `CanonicalSourceBundle`, and keeps warnings separate from
structural parse errors. The outcome-definition approval fingerprint now also
includes `segment_dimension`, so completeness and approvals stale when that
business dimension changes. No Streamlit import UI, persistence migration,
model treatment, posterior aggregation, or causal-graph behaviour is added in
this package. Business question: what does each supplied Outcomes column mean,
and which explicitly declared rows form one measure? Estimand: none
introduced; source values remain supplied observations. Output scale/units:
preserved from the canonical definitions; no NBT reconstruction or rate/index
sum is performed. Upstream modelling references: none consulted; no modelling
API or dependency changed.
**Remaining limitation:** draft seeding/adoption, durable group persistence,
fit treatment, draw-level totals, DNA alternative protection, templates/demo
refresh, and end-to-end UX remain in WP3-WP8. v1 definitions remain excluded
from newly governed fits until reviewed.
**Owner:** Data Science / Platform engineering.
**Status:** Implemented in source-pack semantics WP2.

## Outcome-group persistence and fit-time staleness (Work Package 3)

**Date:** 2026-08-14
**Decision:** Extend the versioned project bundle with separate JSON records
for semantic `OutcomeGroupDefinition` objects, analyst-selected
`OutcomeGroupTreatment` values, and explicitly durable diagnostic
`OutcomeReconciliationGroup` relationships. Missing records in legacy bundles
mean that no groups or treatments were persisted; they do not trigger
inference. Missing group treatment remains the safe `unconfigured` state.
Persist group and treatment snapshots in `FHModelMeta` so a fitted model
retains the historical outcome structure and analyst treatment used at fit.
Include calculation-relevant group membership and treatment values in model
identity; exclude group labels and record schema versions. Reuse the existing
fingerprint and drift architecture, and quarantine malformed imported records
with explicit warnings.
**Reason:** A current source dictionary must never be used to reconstruct the
structure of a historical fit. Semantic grouping, analyst fit treatment, and
diagnostic reconciliation have different ownership and must remain separately
auditable through export/import and stale-state checks. Legacy bundles must
remain loadable with visible absence rather than guessed meaning.
**Alternatives considered:** Store groups only in page/session state (rejected
- the project bundle is the system of record); put fit treatment in the source
dictionary (rejected - it is an analyst model decision); reuse one generic
group record for treatment and reconciliation (rejected - that conflates
business semantics, model structure, and arithmetic diagnostics); silently
repair malformed imported records (rejected - records are quarantined with a
warning).
**Impact:** Bundle schema version 16 persists the three distinct records and
fit metadata round-trips them. Group membership/treatment drift can block
dependent calculations through the existing outcome drift predicate, while a
group-label edit does not stale identity. No model equation or Streamlit
workflow is changed in this package. Business question: can a project resume
with the exact semantic groups, fit treatment, and diagnostic relationships
that existed when its evidence was created? Estimand: none introduced;
persistence and identity metadata only. Output scale/units: unchanged; group
records carry supplied outcome identities and no numerical aggregation is
performed here. Upstream modelling references: none consulted; no modelling
API or dependency changed.
**Remaining limitation:** model-structure UI adoption and actual
`components_joint`/`total_only` fitting remain in WP5; draw-level grouped
totals remain in WP6. Reconciliation is persisted as labelled diagnostic
evidence, not as a fitted likelihood or causal edge.
**Owner:** Data Science / Platform engineering.
**Status:** Implemented in persistence and staleness WP3.

## Outcomes source import and draft catalogue adoption (Work Package 4)

**Date:** 2026-08-14
**Decision:** Interpret a valid `standard-source-pack-v2` Outcomes workbook
through the canonical source bundle and retain its definitions, semantic groups,
diagnostic reconciliation records, and completeness metadata as a separate
source draft. When no outcome catalogue exists, seed those canonical records as
an unapproved draft so analysts do not retype dictionary meaning. When a
catalogue already exists, retain it unchanged and show a calculation-relevant
source/current comparison; adoption requires an explicit analyst action. A v1
workbook remains loadable but is marked legacy/incomplete and contributes no
seeded semantic definitions. Import and adoption never create an
`OutcomeApproval` or choose a group treatment.
**Reason:** Source metadata and the governed catalogue are related but are not
the same authority at upload time. Automatic overwrite could silently change
the meaning of an existing fit, while automatic approval would bypass the
existing outcome-governance contract. The v1 compatibility path must remain
visible rather than inferring business meaning from IDs.
**Alternatives considered:** overwrite the live catalogue on every upload
(rejected - it destroys reviewable current state); silently merge source rows
(rejected - additions and calculation-relevant changes need explicit review);
infer v1 dimensions/groups from names (rejected - the approved contract
forbids ID-based semantic inference); create approvals during import (rejected
- approval is a separate governed action).
**Impact:** `core.outcome_import` provides a portable source interpretation,
catalogue comparison, and explicit draft-adoption payload. Data Sources now
canonicalises Outcomes uploads, seeds an empty catalogue as a draft, exposes a
human-readable comparison for an existing catalogue, and clearly reports v1
incompleteness. Project export/import now carries the WP3 group, treatment, and
reconciliation state through the UI. No model equations, fit treatment, or
posterior aggregation changed. Business question: can a supplied Outcomes
dictionary be reviewed and adopted without re-entry or silent catalogue
replacement? Estimand: none introduced; imported values remain supplied source
observations. Output scale/units: unchanged and governed by each canonical
definition; no approval or causal edge is created.
**Upstream modelling references:** none consulted; this package changes source
interpretation and workflow state only, not modelling APIs.
**Remaining limitation:** group fit-treatment controls, draw-level grouped
totals, DNA alternative protection, downloadable templates, realistic source
pack refresh, and full end-to-end UX remain in WP5-WP8.
**Owner:** Data Science / Platform engineering.
**Status:** Implemented in source import and draft catalogue WP4.

## Model Structure outcome-group treatment (Work Package 5)

**Date:** 2026-08-14
**Decision:** Keep `OutcomeGroupDefinition` as source-semantic membership and
expose `OutcomeGroupTreatment` as a separate Model Structure choice. The
Structure page presents Product, Metric, Breakdown, Segment, source context,
readable group members, and the four governed treatments: `components_joint`,
`total_only`, `descriptive_only`, and `unconfigured`. `components_joint`
requires every member to remain in the next fit and excludes an exact supplied
total from that fit; the supplied total may remain reconciliation evidence.
`total_only` requires a supplied total in the next fit and excludes its
components. Two explicitly distinct DNA breakdowns with the same product and
metric family cannot both receive additive treatments; one must remain
descriptive-only or an explicitly approved joint structure must be introduced.
**Reason:** The source dictionary must not silently select a statistical
treatment, and exact totals/components or alternative DNA partitions must not
enter downstream objectives as unrelated additive outcomes. The unconfigured
state remains a safe, visible import state rather than an inferred choice.
**Alternatives considered:** Infer `components_joint` from group membership
(rejected - source meaning and analyst model treatment have different owners);
fit supplied totals and components together (rejected - exact duplicate
quantity); add all DNA breakdowns (rejected - alternative partitions can
overlap); infer overlap from outcome IDs (rejected - explicit product, metric
family, breakdown, and treatment are the governed signals).
**Impact:** `validate_outcome_group_treatments` now provides framework-
independent total/component and alternative-DNA protection. Structure persists
groups and treatments separately and retains the existing human-readable
outcome UX; legacy projects without groups continue without inferred grouping.
No model equations or posterior aggregation were changed. Business question:
which compatible outcome rows should the next model structure treat as a joint
partition, supplied total, descriptive view, or not-yet-configured group?
Estimand: none introduced in WP5; treatment controls model-structure intent,
while draw-level grouped estimation/reporting remains WP6. Output scale/units:
unchanged supplied outcome counts/values; no medians or intervals are summed
in this package.
**Upstream modelling references:** none consulted; this package changes
framework-independent configuration validation and presentation only, not
PyMC/PyMC-Marketing model APIs.
**Remaining limitation:** WP6 still owns draw-level grouped totals and
downstream Results/attribution/scenario integration; WP7 owns broader DNA
alternative and multi-target halo regression; templates/demo refresh remains
in WP8.
**Owner:** Data Science / Platform engineering.
**Status:** Implemented in Model Structure group treatment WP5.

## Draw-level grouped outcome totals (Work Package 6)

**Date:** 2026-08-14
**Decision:** Add one framework-independent draw-table service for semantic
outcome groups. For `components_joint`, member outcome rows are summed at the
full reporting grain within each posterior draw and only then summarised. For
`total_only`, the supplied total is the official group row and the member rows
are excluded from that view. An exact supplied total under
`components_joint` remains reconciliation evidence rather than an unrelated
official component. Group rows carry stable group identity, human label,
treatment, source, and member identities; cost-bearing fields use one
deduplicated channel/plan value rather than multiplying spend by the number
of members. Projects without groups, or groups that cannot be materialised in
an outcome-scoped artifact, retain the prior row-level behaviour.
**Reason:** Posterior medians and interval endpoints are not additive
quantities. Summing them after independent component summaries can produce a
different business total and can double count exact supplied totals,
alternative partitions, or channel spend. The same service must support GSA,
sign-up, NBT-count, DNA-kit, and future compatible count groups without
embedding FH-specific logic in the model equations.
**Alternatives considered:** Sum already summarised component means and
interval endpoints (rejected - violates posterior-draw aggregation); add
group rows alongside all member rows in official views (rejected - double
counts objectives and reporting totals); use the live source dictionary to
reconstruct a historical fit (rejected - fit-time group metadata is already
persisted and authoritative); change the PyMC equations (rejected - no
verified modelling defect requires it in this package).
**Impact:** `core.outcome_group_totals` now provides draw aggregation,
post-aggregation summaries, member-share reconciliation, safe selectors, and
legacy fallback. Canonical curve governance views, reporting rollups,
shared/market-specific attribution summaries, Results selectors, and
posterior scenario summaries consume fit-time group/treatment metadata. Raw
scenario draws remain available for paired baseline probabilities. Business
question: what is the posterior distribution of one approved grouped measure
after its fitted component outcomes are combined? Estimand: the
outcome-scale additive group response/value at a fixed market/channel/period
and posterior draw, or the supplied total under `total_only`; no log-scale
eta total is exposed as a business response. Output scale/units: the group's
declared outcome unit and, where governed, its additive value currency;
channel/plan spend is counted once. Upstream modelling references: none
consulted; WP6 changes downstream table aggregation and does not change
PyMC/PyMC-Marketing model equations, transformations, or priors.
**Remaining limitation:** alternative DNA partition governance and explicit
multi-target halo regression remain in WP7; downloadable v2 templates,
realistic source fixtures, and full end-to-end UX remain in WP8. A grouped
total is still subject to the same outcome approval, value-weight, currency,
and reporting/optimisation eligibility gates as its source components.
**Owner:** Data Science / Platform engineering.
**Status:** Implemented in draw-level grouped totals WP6.

## DNA alternatives and multi-target halo regression (Work Package 7)

**Date:** 2026-08-14
**Requirement:** `REQ-DATAIN-002`; `Ancestry_MMM_Outcome_Source_Grouping_Coding_LLM_Instructions_FRESH_2026-08-14_0712.md`, WP7.

**Business question:** Can DNA outcomes be partitioned by customer relationship,
purchase recipient, and optional activation status without conflating those
dimensions, while allowing one DNA media pathway to target multiple explicitly
approved Family History outcomes?

**Decision:** DNA alternatives remain governed outcome-group definitions. The
three dimensions are represented independently and cannot be relabelled across
dimensions. Alternative partitions cannot both be selected as additive members,
and unresolved or diagnostic DNA states cannot silently enter additive
treatment. The approved causal graph remains authoritative for halo targets:
each explicit target outcome ID is retained independently, with no edge inferred
from the outcome dictionary. Imported draft outcomes may seed labelled graph
candidate nodes, but remain draft candidates until adopted and included in the
fitted outcome catalogue. Approved graph targets absent from that catalogue fail
closed at model compilation. When no equivalent approved graph exists, the
legacy single-target pathway remains compatible.

**Estimand:** No new model equation is introduced. For an approved graph, each
DNA-media-to-outcome halo edge maps to its own outcome-scale pathway mask and
target outcome ID; no post-hoc target collapse or inferred mediation is used.

**Output scale and units:** Existing approved outcome counts/value units are
unchanged. Stable outcome IDs are persisted internally; human-readable product,
segment, metric, breakdown, version, and draft-candidate labels are presentation
metadata only.

**Upstream references:** None consulted. WP7 does not change PyMC/PyMC-Marketing
model equations, transformations, priors, or sampling APIs; it extends the
existing governed graph compiler, outcome-group validation, and graph-page
candidate workflow.

**Tests:** Added DNA dimension/overlap/diagnostic safeguards, distinct
multi-target halo regression, graph fit-scope guard, legacy no-graph compatibility,
and causal-graph AppTest coverage. Focused validation passed: 257 core/graph
tests and the dedicated 16-test WP7/page run, with Ruff format/check clean.

**Remaining limitations:** This work intentionally does not classify customers
or infer customer-level DNA identity from aggregate sources. Draft candidates
remain non-fitting until governed adoption and fitting. Full CI remains the
release gate.

**Owner:** Data Science / Platform engineering.
**Status:** Implemented in DNA alternatives and multi-target halo regression WP7.

## Downloadable templates and realistic source-pack UX (Work Package 8)

**Date:** 2026-08-14
**Requirement:** `REQ-DATAIN-001`, `REQ-DATAIN-002`; `Ancestry_MMM_Outcome_Source_Grouping_Coding_LLM_Instructions_FRESH_2026-08-14_0712.md`, WP8.

**Business question:** Can a source provider download understandable,
domain-specific workbooks and see a realistic synthetic pack that demonstrates
the governed Outcomes contract without needing to understand analyst or model
internals?

**Decision:** Generate four separate standard workbooks from the existing
domain contracts. The Outcomes download is explicitly
`standard-source-pack-v2` and contains non-production examples for Family
History GSA and sign-up by New, DNA cross-sell, and Winback, plus DNA kit-sale
partitions by customer relationship and purchase recipient. Activity and Media,
Context and External Factors, and Experiment Evidence remain separate logical
workbooks. The optional `outcome_completeness` sheet is omitted from the
template; help tells users to remove optional sheets rather than leave a
parser-invalid empty sheet. The realistic source pack uses canonical field
names and preserves the two DNA dimensions as distinct groups.

**Estimand:** None introduced. Template rows are synthetic examples only and
must not be treated as observed business outcomes or model estimates.

**Output scale and units:** Downloaded files are Excel workbooks. Outcome
examples carry explicit count units, metric keys, segment dimensions, group
identities, and canonical definition metadata; example values are placeholders,
not production Ancestry values.

**Upstream references:** None consulted. WP8 composes the repository's existing
standard workbook parser and canonicalisation contracts; it does not alter
PyMC/PyMC-Marketing model equations, transformations, priors, or sampling APIs.

**Tests:** Added valid-workbook and v2 semantic template tests, canonical
realistic-pack tests, Data Sources download AppTests, upload/lifecycle/export
regressions, and a real-browser assertion for the Outcomes template download.
Focused validation passed: 25 source/template tests, 6 Data Sources AppTests,
21 upload/lifecycle/export tests, and 1 browser lifecycle test.

**Remaining limitations:** Template values are synthetic examples and require
replacement and governance before official use. No customer-level classification
or NBT completeness example is invented by this work package.

**Owner:** Data Science / Platform engineering.
**Status:** Implemented in downloadable templates and realistic source-pack UX WP8.

## Standard source-pack semantic parity (Work Package 3)

**Date:** 2026-08-14
**Requirement:** `REQ-DATAIN-001`; task-specific source-pack parity brief, WP3.

**Decision:** Keep the four logical domains on one source-pack workflow and
adopt each domain at its existing governed boundary. Activity workbooks adopt
`ActivityDefinition` and explicit model-input semantics while leaving the
existing market/channel media-unit and cost registries authoritative. Context
workbooks retain native tidy evidence and metadata, with a lossless wide frame
only at the model-input boundary. Experiment workbooks remain
`source_evidence_only` until an approved evidence registry exists. Outcomes
continue to use the existing Outcomes v2 contract.

Multiple physical workbooks merge only when period × market keys and
overlapping values are compatible; conflicts fail closed. Market remains a row
dimension, `pooling_group_id` remains identity-only, and no calibration,
frequency conversion, fill, or planning mapping is inferred.

**Estimand:** None introduced. The adopted frames preserve source-scale
observations and missingness. Official preparation remains the WP2 native
frequency and consumed-variable gate.

**Output scale and units:** Source-native units, explicit model-input kind/unit,
spend/response-unit columns, currency, and effective-period metadata are
retained as source evidence. Model economics still requires the existing
governed media-unit/cost mapping.

**Upstream references:** None consulted. WP3 composes existing repository
contracts and does not change PyMC/PyMC-Marketing equations, transformations,
priors, or sampling APIs.

**Tests:** Added source-pack parser/adoption, multi-market and multi-domain
merge, mixed-frequency fail-closed, experiment evidence, and persistence
round-trip coverage. Focused source/template validation passed; full CI remains
the release gate.

**Remaining limitations:** The current official executor supports the adopted
weekly native path only. Non-weekly context needs an approved conversion
method, and experiment calibration must use a separately governed registry.

**Owner:** Data Science / Platform engineering.
**Status:** Implemented in canonical standard source-pack adoption WP3.

## Official UK lifecycle readiness harness (Work Package 5)

**Date:** 2026-08-14
**Requirement:** Task-specific official UK lifecycle readiness brief, WP5.

**Decision:** Add one framework-independent, local-only readiness command that
composes the existing source-pack parser/adoption boundary, native weekly
official-preparation gate, coverage/engine capability evidence, and the
existing deterministic fitted lifecycle bundle. Synthetic CI mode exercises
the full deterministic lifecycle without live sampling. Real source and
bundle modes report safe metadata, fingerprints, counts, timings, and
governance status, then stop at unresolved decisions; they never infer a
frequency method, coverage treatment, model approval, or causal/Search method.
All generated readiness outputs are directed to an explicit D-drive path.

**Estimand:** None introduced. The harness is an orchestration and evidence
boundary; it does not estimate outcomes or causal effects.

**Output scale and units:** Metadata only: source/schema identity, SHA-256
fingerprints, row/column/missing-cell counts, date bounds, market counts,
stage statuses, and elapsed seconds. No source-row values are written to the
report.

**Upstream references:** None. WP5 composes repository-controlled source,
official-preparation, persistence, and lifecycle contracts; it does not alter
PyMC or PyMC-Marketing model equations or dependency versions.

**Tests:** Added D-drive/path guard, synthetic pass, mixed-frequency
fail-closed, coverage-gap decision-required, local-source identity, and
metadata-only report tests. Added the synthetic command to the Windows CI
tooling job.

**Remaining limitations:** The real UK run still requires approved decisions
for mixed-frequency treatment by variable class, ragged-window mathematics and
engine support, production Search mediation/capacity mathematics, and any
graph roles not supported by the selected engine. This work package records
those as blockers; it does not recommend a statistical option.

**Owner:** Data Science / Platform engineering.
**Status:** Implemented as a local readiness harness; real UK execution remains
analyst-authorised and decision-gated.

## Repository truth reconciliation before mixed-frequency execution (Work Package 0)

**Date:** 2026-08-15.

**Decision:** Reconcile current-status documentation to the merged repository
at `main` `19fd12416cd882980bc83607f2f7677de38f4d48` (UX Phase 6, PR #248).
The status documents now describe canonical native-weekly official preparation,
its governed outer-union calendar, fit-consumed-variable capability gating,
standard source-pack semantic adoption, the current source-pack UX, and the
graph/Search governance state as delivered. Historical dated snapshots in
`REQ-COVERAGE-001` remain labelled as historical rather than being rewritten.

The remaining mixed-frequency gap is specifically executable, approved
variable-class conversion: the registry is still empty and unsupported
monthly, quarterly, survey, and irregular official inputs remain fail-closed.
Ragged market-specific predictor mathematics, production Search mediation and
capacity/censoring, the sequential weekly planner, future exogenous forecasting,
and real UK validation remain unresolved or operationally gated.

**Estimand:** None introduced. This package changes documentation and traceability
only; no source preparation, model, persistence schema, governance decision, or
planning calculation changes.

**Upstream references:** None consulted; no modelling dependency or external API
was changed.

**Tests:** Requirements/documentation conformance tests and the normal formatting,
compile, and diff checks for edited files are the validation gate for this package.

**Owner:** Data Science / Platform engineering.
**Status:** Implemented as documentation reconciliation; Work Package 1 remains
the next unblocked package.

## Explicit mixed-frequency catalogue and official executor (Work Package 1)

**Date:** 2026-08-15.

**Requirement:** Task-specific “Media-Mix-Lab: Coding LLM Next Steps”
implementation brief, WP1.

**Decision:** Implement a narrow, framework-independent mixed-frequency
catalogue and executor behind the existing canonical-calendar and official-
preparation contracts. The Coverage review must persist an explicit variable
class, method ID, method version, parameters, publication timing, support and
effective boundaries, definition breaks, and reconciliation rule. The approved
WP1 method families are calendar-day overlap allocation for flow counts,
release-aware LOCF for stock/rate/survey measures, native-cadence-only survey
retention, and explicit point/duration event alignment. Missing method IDs,
version mismatches, leakage, definition-break crossings, invalid inputs, and
reconciliation failures remain blocking errors. Native frames and the
exploratory Transform Pipeline are not overwritten.

**Estimand:** None introduced. The converted output is a weekly source-scale
model input: flow totals reconcile to the source total; levels/rates/surveys
carry only released observations; events retain point placement or active-day
fractions. No MMM likelihood, link, outcome, or causal estimand changed.

**Output scale and units:** Source units are preserved. Flow allocation is by
calendar-day fraction; duration-event output is a fraction of an event week;
LOCF values remain in the source unit and include observation-age evidence.

**Upstream references:** Locked `pandas==3.0.3`; official pandas period and
calendar APIs recorded in `docs/mixed_frequency_alignment_wp1.md`. Context7
was unavailable. No PyMC or PyMC-Marketing API changed.

**Tests:** Added synthetic mixed-frequency fixture and requirement-tagged
tests for leap-year/month boundaries, release timing and no backward fill,
definition breaks, point/duration events, missingness, method metadata and
matrix round trips, official readiness, and source-pack mixed-cadence review.
Focused executor, coverage/fingerprint/persistence, source-pack, and UI
AppTests passed locally on the D-drive environment.

**Remaining limitations:** WP1 targets the governed weekly calendar and does
not provide generic interpolation, ragged market mathematics, production
mediation/censoring, or future endogenous-mediator forecasting. Real UK
end-to-end validation remains deferred pending source-data availability.

**Owner:** Data Science / Platform engineering.
**Status:** Implemented on the WP1 branch; PR and CI remain the release gate.
## Search mediation and capacity decision package (Work Package 3)

**Date:** 2026-08-15.

**Decision:** Add a self-contained, decision-support-only synthetic harness
and decision document comparing three explicit Search formulations: structural
latent demand with a hard cap, probabilistic capture with cap-aware censoring,
and a reduced-form diagnostic benchmark. Preserve the existing governed
identities for branded-search demand, Paid Search spend, Paid Search delivery,
Paid Search cap, organic capture, direct navigation, final outcome, and
residual Paid Search incrementality as an output. Do not enable mediated or
capacity-constrained graph edges.

**Estimand and output scale:** The synthetic contract evaluates direct
outcome-scale effect, realised mediated/captured outcome effect, captured and
unmet demand volumes, realised total outcome effect, and unconstrained
potential outcome effect. It enforces `captured + unmet = latent`; unmet
potential is diagnostic and is not added to realised total response.

**Evidence:** Deterministic known-truth fixtures cover never-binding,
sometimes-binding, heavily-binding, upstream-media/cap limitation,
organic/direct absorption, and high-association/low-incremental-capture cases.
Candidate A recovers the forward equations exactly and raising a non-binding
cap creates no delivery or capture. This is contract-level forward recovery,
not posterior parameter recovery or an identifiability claim.

**Upstream references:** Official PyMC `Censored` and `NegativeBinomial`
documentation and the pinned PyMC-Marketing 0.19.4 MMM package were reviewed.
Standard MMM transformations, priors, posterior prediction, curves,
calibration, and optimisation are upstream-supported; the bespoke latent
demand/capacity/censoring graph, decomposition, and governance remain custom
and require an approved linked-model design.

**Decision gate:** Human approval is still required to select the production
formulation and approve its likelihood, estimand, hierarchy/priors,
identification/data requirements, posterior/planning outputs, and failure
states. No production Search implementation starts until that decision is
recorded in an approved repository decision record and scoped brief.

**Owner:** Data Science / Platform engineering.
**Status:** Decision-support package; production formulation unresolved.

## Candidate A Search mediation and capacity approval (Work Package 4)

**Date:** 2026-08-15.

**Decision:** Candidate A, the structural latent-demand formulation with an
explicit hard Paid Search cap, is approved as the first production Search
mediation/capacity formulation. Candidate C remains available only as a
diagnostic/sensitivity benchmark. Candidate B is not implemented at this
stage.

This is approval to implement and validate the architecture. It is not
approval of the resulting Search estimates for official planning use. The
implementation is governed by `REQ-SEARCH-002` and must preserve all seven
Search identities from `REQ-SEARCH-001`; it must not create a generic Brand
Search variable, treat Paid Search delivery as demand, or treat a cap as
guaranteed spend/delivery. The demand reconciliation, separate organic and
direct capture, direct upstream pathway, explicit counterfactual effects,
posterior-draw aggregation, and fail-closed identification requirements are
part of the approved implementation contract.

Candidate A is a custom linked PyMC engine capability. The ordinary
PyMC-hierarchical graph engine remains closed to mediated and
capacity-constrained structures, and unrelated mediated/capacity structures
remain unsupported. Search planning and cap optimisation remain disabled
until noisy recovery, prior/posterior predictive, identification,
counterfactual-contract, and explicit model-approval gates all pass.

**Upstream alignment:** PyMC `v5.28.5` `Censored` and
`NegativeBinomial`, plus PyMC-Marketing `v0.19.4` public MMM APIs, were
reviewed. They cover general Bayesian likelihood/sampling and standard MMM
transformations; the governed Search objects, Candidate A structural
reconciliation, graph extension, and identification gates are custom. The
project therefore continues to use the claim “Built in PyMC and informed by
PyMC Marketing.”

**Owner:** Data Science / Platform engineering.
**Status:** Approved for implementation; planning/optimisation eligibility
remains disabled.

## Candidate A synthetic generator and recovery-evidence policy (Work Package 2)

**Date:** 2026-08-15.

**Decision:** Add a synthetic generator (`core.search_candidate_a_recovery`)
that independently computes the Candidate A forward equations in NumPy
(reusing only the reference `core.transformations` adstock/Hill functions,
never the PyMC/PyTensor implementation itself), and evidence-grade
infrastructure - fast prior-predictive plausibility checks, a real
`pm.sample` NUTS posterior-recovery suite against the *integrated*
production model (`core.hierarchical_model.build_fh_hierarchical_model(...,
search_candidate_a=...)`), and a deterministic identification-sensitivity
sweep - covering multiple channels with distinct adstock/saturation, a
direct-only channel (`demand_beta=0.0`), a mediated channel, all three cap
regimes (never/sometimes/frequently binding), multi-market support, and
noisy observations.

**Interval-coverage evidence, not point recovery:** posterior-recovery
checks assert the true value falls inside a reported credible interval
(with slack), not exact point recovery, per the approved brief's own
guidance for weakly identified parameters. `CandidateARecoveryPolicy`
(`core.search_candidate_a_recovery.CANDIDATE_A_RECOVERY_POLICY`) records
this as a versioned (`wp2-v1`), scoped evidence bar - engine-capability
evidence only, explicitly not an official-use, planning, or optimisation
approval. `core.search_capacity.candidate_a_use_gate` remains the single
official-use gate; this package supplies one of its required evidence
inputs (`noisy_recovery_passed`), which still requires an explicit
human/process decision to set.

**Identification finding:** the approved Candidate A graph contract
(`core.graph_model_compiler.candidate_a_graph_issues`, REQ-SEARCH-002)
requires every upstream intervention node to carry a mediated edge into
latent demand - a graph cannot mix demand-mediating and plain-direct-only
intervention nodes structurally. A "direct-only" channel is therefore
expressed as a demand-mediating node whose true `demand_beta` is zero, not
by omitting it from the mediated structure. Separately, noisy delivery
observation was found to measurably degrade `identify_candidate_a_search`'s
exact-equality cap-binding detection (`np.isclose(..., rtol=1e-8,
atol=1e-8)`) - a real, if narrow, identification-sensitivity finding
recorded in `test_search_candidate_a_recovery.py`, not treated as a defect
to fix in this package.

**Real MCMC recovery could not be run locally by the implementing agent:**
PyTensor's Python compilation fallback (no C++ compiler available in that
environment) fails with `AttributeError: 'Scratchpad' object has no
attribute 'ufunc'` once a model's summed log-probability graph exceeds a
NumPy ufunc argument-count ceiling - reproducible even with a minimal
single-channel Candidate A model, and confirmed to be an environment
limitation (not a Candidate A-specific defect) since the *ordinary*,
unmodified hierarchical model hits the same underlying warning once its own
free-parameter count grows. The forward/deterministic graph (reconciliation,
non-binding-cap invariant, prior-predictive plausibility) was verified
locally via `pm.draw`/`pm.sample_prior_predictive`, which do not require
gradient/logp compilation. The real `pm.sample` suite
(`test_search_candidate_a_recovery_posterior.py`) is verified by the CI
runner instead (`candidate-a-recovery` workflow job), which is expected to
have a working C toolchain.

**Owner:** Data Science / Platform engineering.
**Status:** Evidence-package delivered. Official Search fit eligibility
remains gated by explicit human/process review of this evidence plus the
remaining `candidate_a_use_gate` requirements (prior/posterior predictive,
counterfactual-contract, explicit model approval) - this package does not
self-approve any of them.

## Candidate A application fit, diagnostics, and reporting workflow (Work Package 3)

**Date:** 2026-08-15.

**Decision:** Fix two silent-correctness gaps discovered while integrating
Candidate A into the application layer, extend posterior extraction and the
canonical Diagnostics artefact with real Candidate A evidence, and formally
defer full Results/Curves/Attribution/Scenario-Planner replay integration
rather than build a rushed, partial version of it.

**Silent-correctness fixes (not new capability - defect closure):**

1. `pages/06_Diagnostics.py::_rebuild_fit_time_model` rebuilt the *ordinary*
   model (dropping the entire Candidate A Search chain) for any fit whose
   approved graph required the Candidate A engine, because it branched on
   `model_type` inline instead of using the engine-selection adapter WP1
   introduced. Now routes through `application.model_fit_service.
   build_model_for_spec`, which fails closed with a specific
   `ModelFitServiceError` instead (no UI yet supplies the Candidate A
   Search observations a correct rebuild would need).
2. `core.attribution.compute_shapley_contributions` and `core.predict.
   predict_mu` (and therefore every downstream caller: canonical curves,
   the Scenario Planner, the optimiser, backtest) reconstruct `mu` from the
   ordinary model's own terms only - neither reads Candidate A's
   `search_eta_contribution`. Before this package, calling either on a
   Candidate A fit produced a `mu`/`mu_total` silently missing the entire
   search-mediated pathway's contribution - no exception, no warning. Both
   now raise a specific, documented exception
   (`CandidateAAttributionNotSupportedError`/
   `CandidateAReplayNotSupportedError`) for a Candidate A fit. This is the
   single mechanism that keeps Results, official curves, the Scenario
   Planner, and optimisation correctly disabled for Candidate A (REQ-
   SEARCH-002: "Search planning and cap optimisation remain disabled") -
   one guard in `predict_mu` protects every downstream consumer at once,
   rather than requiring a separate gate in each.

**New evidence surfaces:**

- `core.search_capacity.extract_candidate_a_search_posterior_summary`:
  posterior-evidence extraction from a fitted Candidate A trace (demand/
  capture-share/outcome-beta means, reconciliation error, cap-binding
  probability, r-hat/ESS for the Search-specific parameters), following the
  established "separate typed extractor for a second model shape" pattern
  (`core.market_specific_predict.extract_market_specific_posterior_params`).
- `DiagnosticsArtefact` schema v6 -> v7 adds a `search_capacity` section,
  `not_applicable` for every ordinary fit, computed inline in
  `DiagnosticsService.evaluate()` for a Candidate A fit from the trace
  alone. Spec-validation/identification/official-use-gate evidence is
  additionally included when a `SearchCandidateASpec` is supplied via the
  new optional `DiagnosticsInput.candidate_a_spec`/
  `candidate_a_search_objects`/`candidate_a_paid_search_cap`/
  `candidate_a_paid_search_delivery` fields - none of which any page
  populates yet (no UI collects a Candidate A spec into session state), so
  today the section reports posterior-summary evidence only, with an
  explicit warning that spec-level evidence is unavailable. A new
  "Candidate A Search" tab on the Diagnostics page renders this section.

**Deferred, with reasons (brief's own permission: "If the existing
attribution algebra cannot represent Candidate A cleanly, add a
Candidate A-specific decomposition contract... If curve governance requires
a new approved artefact contract, create a decision-support record rather
than inventing one"):**

- **Full replay integration** (extending `predict_mu`/
  `steady_state_outcome_response` with the Search chain) - the prerequisite
  for Results, official curves, the Scenario Planner, and optimisation to
  work for Candidate A at all. Not attempted here: it requires deciding how
  a *hypothetical* scenario/curve spend point maps to a *counterfactual*
  Search demand/capture/cap state (the model's `search_*` deterministics
  are fit-time quantities over historical `sat_media`, not a function
  `predict_mu` can currently re-evaluate at an arbitrary candidate spend
  level) - a genuine modelling design question, not a mechanical
  extension, and out of scope for an application-layer work package.
- **Candidate A-specific Shapley/attribution decomposition** - blocked by
  the same replay-integration prerequisite above (direct/mediated/total
  effects need the same counterfactual re-evaluation machinery).
- **Official curve artefact contract for Candidate A** - REQ-CURVE-001's
  `generate_canonical_curve_draws` reads `meta.pathway_masks.components`,
  which `GraphModelCompiler(engine=SEARCH_CANDIDATE_A_ENGINE)` deliberately
  excludes the search-mediated pathway from (REQ-SEARCH-002's approved
  graph contract) - Candidate A's demand/capture/cap chain has no
  representation in the canonical curve contract's data model at all, not
  merely an extraction gap. A Candidate A curve (per the brief's own
  requirement) would need to identify what's varied, what cap is held
  fixed, and whether the cap is binding - a new artefact shape, not an
  extension of the existing one.
- **Convergence section's Candidate A parameters** -
  `DiagnosticsService._check_convergence` uses an explicit `var_names`
  allowlist (`mu`, `beta`, `hill_K`, `alpha`) that excludes every Candidate
  A variable; not extended here because the new `search_capacity` section's
  own `rhat_max`/`ess_bulk_min` already surfaces Candidate A-specific
  convergence evidence separately - judged sufficient for this package
  rather than duplicating it in two sections.

**Owner:** Data Science / Platform engineering.
**Status:** Silent-correctness defects closed; new evidence surfaces
delivered. Search planning, cap optimisation, Results, official curves,
and attribution remain disabled/unavailable for Candidate A - not a partial
or approximate implementation of any of them.

## Targeted structural and test hardening (Work Package 4)

**Date:** 2026-08-16.

**Decision:** Close the single largest repeated full-core mypy debt
pattern with a characterization-tested, zero-behaviour-change fix, and fix
a real local-vs-CI test drift this work session itself introduced.

**mypy debt reduction (276 -> 245, 31 errors closed):**
`FHModelMeta.pathway_masks: Optional[ResolvedPathwayMasks]` is guaranteed
non-`None` after `__post_init__` runs (it always resolves to a real object
when `None` is passed, and nothing outside `__post_init__` ever reassigns
it - confirmed by an exhaustive grep across the package before making this
change). Despite that runtime guarantee, every call site that read
`meta.pathway_masks.<method>()` across `core/attribution.py`,
`core/market_specific_attribution.py`, `core/predict.py`, and
`core/market_specific_predict.py` was flagged by mypy (`Item "None" of
"ResolvedPathwayMasks | None" has no attribute ...`), since mypy cannot
infer a `__post_init__`-established invariant across call boundaries. Added
`FHModelMeta.resolved_pathway_masks` - a property that asserts the
(always-true) non-`None` invariant once and returns the narrowed type -
and updated the four call sites to use it. Characterization tests
(`TestFHModelMetaResolvedPathwayMasks`) were added before the mechanical
replacement, proving the property returns the exact same object
`pathway_masks` already held (identity, not a copy) both for the
`__post_init__`-resolved default case and an explicitly-passed value. Pure
type-narrowing - no behavioural change; full regression sweep across the
four touched files plus `core/canonical_curves.py`/`core/optimization.py`/
`core/market_specific_model.py`/`core/search_capacity.py` (275 tests) all
green. `.mypy-baseline-count` lowered from 276 to 245 to lock the
improvement in, per the CI ratchet's own instruction ("lower
.mypy-baseline-count to $current to lock the improvement in"). GitHub
issue #123 updated to match.

**Local test-suite drift (self-inflicted, found and fixed):**
`scripts/run_full_test_suite.ps1` (the single documented local entry point
for the real 75% coverage floor) had silently drifted out of sync with
`.github/workflows/tests.yml`'s Python 3.11/3.12 job commands: Work
Package 2 added `test_search_candidate_a_recovery_posterior.py` (real
`pm.sample` NUTS fits, ~7-8 minutes on CI's compiler-equipped runner) to
the CI ignore list but not to this local wrapper. Without a C compiler
available - not unusual on a bare Windows dev machine - PyTensor's Python
compilation fallback can outright fail on this file's larger models
(`AttributeError: 'Scratchpad' object has no attribute 'ufunc'`, first
observed in WP2) rather than merely running slowly, so an unmodified local
full-suite run could hang or error out entirely, not just take longer than
CI's ~9 minutes. Added the matching `--ignore` flag and documented why in
the script's own header, alongside the pre-existing (undocumented until
now) `test_persistence.py`/browser-journey exclusions.

**Other likely contributors to local-vs-CI runtime gap, not addressed
here:** no `pytest-xdist`/parallelisation is configured anywhere in the
project (verified: no reference in `pyproject.toml`, `uv.lock`, or CI);
Windows filesystem/antivirus overhead on thousands of small file
operations (coverage instrumentation, node-id collection) is a well-known
Windows-vs-Linux-runner gap unrelated to this codebase. Adding
`pytest-xdist` locally is a plausible next step (the brief explicitly
permits "deterministic safe parallelisation"), but verifying the ~3,000-
test suite has no shared-state/ordering assumptions that would break under
parallel execution is its own, separate investigation - not attempted in
this targeted work package to avoid conflating a mypy-debt/correctness
package with an unverified test-infrastructure change.

**Owner:** Data Science / Platform engineering.
**Status:** mypy ceiling lowered and locked in; local wrapper drift fixed.
Broader local-suite parallelisation remains a documented, not yet
attempted, follow-up.

## Sequential simulation kernel (Work Package 5)

**Date:** 2026-08-16.

**Decision:** Implement `ancestry_mmm/core/sequential_simulation.py`, a
framework-independent weekly state-transition engine for the currently
production-supported pathways (`core.hierarchical_model.
build_fh_hierarchical_model` / Model A, and `core.market_specific_model` /
Model C), sitting alongside - never replacing - the existing steady-state
planner (`core.optimization`, `core.predict.steady_state_outcome_response`).
This directly closes the gap `core/AGENTS.md`'s "Steady-state versus
sequential" section and `REPO_REVIEW_AND_NEXT_STEPS.md` both named:
"Scenario planning remains a steady-state monthly approximation rather than
a sequential weekly simulation with starting adstock and terminal
carryover."

**Design - reuse over reimplementation (AGENTS.md's explicit instruction):**
rather than a parallel adstock/eta implementation, this work made two
small, additive, backward-compatible extensions to already-shipped
production code and built the new kernel on top of them:

1. `core.transformations.geometric_adstock`/`geometric_adstock_matrix`
   gained an `initial_state` parameter (default `0.0`/`None`, reproducing
   today's from-scratch behaviour exactly). Continuing the recursion from a
   real ending state and normalising only the new segment is mathematically
   exact - not an approximation - versus normalising the whole concatenated
   series in one call and slicing (proved directly by
   `TestGeometricAdstockInitialState` in `test_transformations.py`, and by
   the sequential kernel's own golden-equivalence tests below).
2. `core.predict.predict_mu`/`core.market_specific_predict.
   predict_mu_market_specific` gained a `precomputed_sat_media` keyword: when
   given, the caller's own adstocked-and-saturated media array is used in
   place of the internal batch computation, while every other term
   (baseline/market/trend/season/promo/controls, and the direct/cross-
   product pathway-masked combination) is computed by the exact same,
   already-tested code path. This is the mechanism that lets the sequential
   kernel's carry-in-seeded `sat_media` flow through `predict_mu` unchanged,
   so the two can never silently diverge for any non-adstock term.

**Upstream reference (AGENTS.md's required upstream-reference workflow):**
`pymc-labs/pymc-marketing` 0.18.1's `GeometricAdstock` is a *finite*
`l_max`-truncated convolution (typical `l_max` 6-8 weekly), and its own
forward-simulation notebooks prime that window by prepending `l_max`
"warm-up" periods into the same array rather than passing an explicit
carry-in state. This repo's `geometric_adstock` is a genuinely infinite-
horizon recursive filter - a pre-existing divergence, not introduced here -
so reproducing upstream's warm-up-prepend pattern would silently truncate
the decay to a finite window, diverging from what was actually fit. An
explicit `initial_state` scalar carried through the same recursive formula
is the correct carry-in mechanism for this repo's own transform (see the
module docstring for the full gap analysis).

**Historical carry-in (brief: "do not assume zero, do not assume steady
state, do not let carryover cross market boundaries"):**
`reconstruct_starting_state`/`reconstruct_starting_state_market_specific`
replay the real historical media through the *same* recursion (`initial_
state=0` only at the market's own true history start, matching
`market_bounds`' existing per-market scoping exactly) to obtain each
channel's real ending raw-adstock value, plus a real historical
adstocked-and-saturated media tail (`lag_context_sat_media`) long enough
to serve the cross-product/halo lag term for the first weeks of a plan
horizon without an incorrect zero-pad. `SequentialCarryInState` represents
both explicitly, plus a `to_adstock_state()` projection onto the existing
`core.planning.value.AdstockState`/`PlanningEvaluationSemantics` governance
objects (kept unused since PR 72F/82E/88B, anticipating this exact work).

**Candidate/reference contract and posterior handling:** `WeeklyPlan` +
`simulate_sequential_outcomes`/`_market_specific` are the same pure
function for both a candidate and a reference run - no-change equality is
therefore an exact floating-point identity, not a tolerance-tuned
approximation (`test_no_change_scenario_invariant_is_zero`, marked release-
blocking per the brief). `simulate_sequential_outcomes_posterior` returns
every sampled draw's full path stacked (`(n_draws, n_weeks, n_outcomes)`),
never a summary - aggregation is the caller's responsibility, matching
`core/AGENTS.md`'s "posterior-draw-level reconciliation before any summary
statistic".

**Terminal carryover:** `simulate_terminal_carryover` continues the exact
same recursion past the plan horizon (typically with
`zero_media_extension_plan`'s all-zero media). It returns a structurally
separate `SequentialSimulationResult` - nothing in this module or in
`core.optimization`'s objective functions folds it into an optimisation
objective.

**Candidate A Search - bounded, unchanged production boundary:** the
outcome-level `simulate_sequential_outcomes` raises
`CandidateAReplayNotSupportedError` for a Candidate A engine fit, exactly
mirroring `predict_mu`'s WP3 guard - wiring `search_eta_contribution` into
a counterfactual forward replay remains the genuine unresolved modelling
design question WP3 already identified (REPO_REVIEW_AND_NEXT_STEPS.md),
not something this package invents a default for. What this package does
add, exactly as the brief specifies ("Candidate A Search state may be
replayable for diagnostic/manual simulation, but Search planning
eligibility remains governed separately"): a new, explicitly diagnostic-
only `simulate_candidate_a_mediator_state_sequentially`, replaying only the
demand/capture/cap chain (never the final outcome) week by week by reusing
`core.search_capacity.candidate_a_forward` directly against a carry-in-
seeded demand series. `core.search_capacity` also gained
`CandidateASequentialDrawParams`/`extract_candidate_a_sequential_params`,
the per-draw analogue of `extract_candidate_a_search_posterior_summary`'s
existing distributional (posterior-mean) read.

**Evidence:** `test_sequential_simulation.py` (26 tests) covers every item
in the brief's required test list, centred on
`TestGoldenEquivalence`: splitting one continuous media series into a
historical prefix and a future plan, and asserting the sequential kernel's
output over the future suffix is bit-identical (`rtol=1e-10`) to
`predict_mu`'s existing batch replay over the whole series - proving
adstock carry-in, Hill saturation, the DNA cross-product/halo lag, and
direct/halo reconciliation are all correct simultaneously against the
model's own already-shipped math, for both Model A and Model C, including
a market that is not first in `meta.markets` (a real market-indexing bug
this test caught during development - see the module's `_assemble_replay_
frame` docstring). Also: zero-media/zero-carry-in baseline, non-zero
historical carry-in changing week-one output, a one-week impulse's decay
and lagged halo landing, no-market-leakage, the no-change candidate/
reference invariant, terminal carryover's decaying residual response as a
separate result, posterior draws returned unaggregated, Candidate A
sequential reconciliation (`captured + unmet == demand`) and the non-
binding-cap invariant (raising a non-binding cap does not change captured
demand), and fail-closed behaviour for a Candidate A engine's outcome-level
replay. `test_transformations.py` separately proves `initial_state`'s
backward compatibility and its exactness versus full-batch recomputation.
Full local suite (CI-equivalent exclusion set): all tests passing. mypy:
245 -> 241 (a genuine `hill_function` signature fix - `K`/`S` accept
`Union[float, np.ndarray]`, matching how every multi-channel caller already
invokes it - retired 4 pre-existing errors at existing call sites while
adding 0 net new ones from this package's own new call sites).

**Scope not covered (explicitly deferred, per the brief):** how a monthly
plan spreads across weeks (WP6); wiring this engine into
`application/scenario_service.py`/`pages/08_Scenario_Planner.py` or
`core.optimization`'s objective (a UI/application integration decision, not
specified by this package); ragged multi-market predictors (WP7) and
time-varying baseline (WP8) remain separately scoped.

**Owner:** Data Science / Platform engineering.
**Status:** Sequential simulation kernel implemented and tested for both
production-supported model types; Candidate A diagnostic mediator-state
replay implemented as a bounded capability. Application-layer integration
(Scenario Planner UI, optimiser objective) is a documented follow-up, not
attempted in this targeted work package.

## Reconcile authority docs and index sequential-planning requirements (Work Package 0)

**Date:** 2026-08-16
**Decision:** Fix documentation drift found in `docs/specification_authority.md`
(falsely claimed the mixed-frequency conversion-method registry is empty -
false since PR #250 - and never referenced `REQ-SEARCH-002` despite it
being approved and indexed since 2026-08-15) and `README.md` (falsely
claimed Candidate A is wholly unwired from Diagnostics - false since
PR #257 - and stated the sequential planner is simply "not built" instead
of distinguishing the implemented kernel from its not-yet-wired Scenario
Planner integration). Create and index four new requirement records:
`REQ-STATE-001` (sequential state contract - retroactive, documents the
already-implemented WP5 kernel), `REQ-SCEN-001` (sequential scenario
evaluation contract - kernel-level implemented, application-level
approved-not-yet-built), `REQ-SCEN-002` (monthly-to-weekly phasing,
`calendar_day_overlap_v1`), `REQ-SCEN-003` (response horizon and terminal
reporting) - the latter two approved for the next work package per the
task-specific brief's standing authority (`Media-Mix-Lab: Coding LLM Next
Steps Post WP5`, 2026-08-16), not yet implemented at the time of this
package. Extend the existing anti-drift test suite
(`test_repository_status_conformance.py`) with tests guarding the drift
just fixed. Add `scripts/wait_for_pr_green_then_merge.ps1` (this repository
has no effective required-check branch protection on `main`, so a bare
`gh pr merge --auto` merges immediately rather than waiting for checks -
exactly what let PR #258 merge red, see the WP4/WP5 entries above) and an
additive, informational-only CI job (`candidate-a-recovery-gate-check`)
flagging when a PR touches Candidate A model files.
**Reason:** Coding agents are required to trust repository-controlled
authority documents over independently reinterpreting the PRD or the
codebase from scratch each time - a stale authority document can cause a
correct agent to stop or implement the wrong boundary. The sequential
kernel's own requirement records were named (`REQ-STATE-001`,
`REQ-SCEN-001`-`003`) throughout `docs/specification_authority.md` before
this package but never actually existed as indexed records - only the
implementation brief served as approval authority for WP0-WP5, which is a
correct but temporary pattern that should not persist once a durable
record can be created.
**Alternatives considered:** Leaving the sequential-planning records
unindexed and continuing to cite the implementation brief as authority
(rejected - the brief is task-specific and will eventually be superseded;
an indexed record is the durable form this repository's own authority
hierarchy expects). Bundling the CI merge-gate script into a later work
package (rejected - PR #258's red-`main` incident already demonstrated
the unsafe-auto-merge gap is a live risk, not a hypothetical one, so
closing it was treated as part of this reconciliation package rather than
deferred further).
**Impact:** `docs/specification_authority.md`, `README.md`,
`REPO_REVIEW_AND_NEXT_STEPS.md` corrected; four new
`docs/approved_requirements/REQ-{STATE-001,SCEN-001,SCEN-002,SCEN-003}.md`
records indexed; `test_repository_status_conformance.py` extended;
`scripts/wait_for_pr_green_then_merge.ps1` added;
`.github/workflows/tests.yml` gained one new, additive, non-blocking job.
No schema, migration, or persisted-field changes. No core/application
Python touched, so no mypy debt impact (241 unchanged).
**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented and merged as PR #261.

## Monthly-to-weekly phasing contract (Work Package 1)

**Date:** 2026-08-16
**Decision:** Implement `REQ-SCEN-002`'s phasing contract in
`ancestry_mmm/core/planning/phasing.py`: `calendar_day_overlap_v1`
(inclusive day-overlap allocation, mirroring
`core.frequency_conversion._calendar_overlap_allocation`'s own day-counting
convention without sharing its code path - a forward-looking business plan
and a backward-looking source-data conversion are governed by different
requirement records), per-month conservation to strict numerical tolerance
(`rtol=atol=1e-10`, matching the existing mixed-frequency executor's own
tolerance), an explicit weekly-schedule override with its own
reconciliation check, and separate monetary (phase spend, then apply a
weekly/period-specific `core.media_costs` mapping resolved per week via
`CostMappingRegistry.resolve(..., as_of=...)`) and model-input-quantity (no
cost conversion) paths. Also implement `REQ-SCEN-003`'s typed
`HorizonConfiguration` contract (short/long/plan/terminal horizons,
explicit values required, no hidden UI-preset constants).
**Reason:** `REQ-SCEN-002`/`REQ-SCEN-003` were approved-but-not-implemented
by WP0; per this repository's convention of small, vertically-scoped work
packages (mirrored throughout this repository's own history - WP1/WP2/WP3
each delivered one coherent slice of Candidate A rather than one combined
PR), this package delivers the phasing module and horizon type only,
explicitly deferring the future-context builder (trend/Fourier/promotions/
controls generation, `REQ-SCEN-002`'s own "Not yet covered" boundary) and
all application-layer wiring to separate, dependent work packages.
**Alternatives considered:** Attributing an explicit weekly schedule's
boundary-week value to overlapping months by a flat day-fraction of the
7-day week (`overlap_days / 7`) - rejected after it was caught failing its
own round-trip test: dividing by 7 unconditionally under-attributes a week
whose *other* days fall in a month absent from the plan (or outside the
calendar entirely) rather than in a second *tracked* month, so a schedule
produced by the governed method's own forward allocation did not reconcile
against itself. Fixed by normalising each week's tracked-month weight by
the sum of that week's day-overlap across only the months present in
`monthly_values` - this exactly reproduces the forward allocation whenever
a week's non-tracked days would otherwise dilute the check, and only
becomes a genuine, irreducible split (day-proportional between the two
tracked months) when a week is shared between two months *both* present in
the plan, which has no unique answer from one scalar without additional
information. Requiring a governed cost mapping for every week in the
monetary path unconditionally (rejected after the same round-trip
discipline caught it): `CanonicalCalendar` is typically a project's full,
multi-year window, not just the months being planned, so most weeks in a
realistic call would have exactly zero phased spend and requiring a cost
mapping for them regardless would fail in ordinary use; a week with exactly
zero spend now needs no mapping at all (unambiguous zero regardless of
cost).
**Impact:** New `ancestry_mmm/core/planning/phasing.py`
(`MethodProvenance`, `MonthReconciliation`, `WeeklyAllocationResult`,
`WeeklyModelInputDerivation`, `MonetaryPhasingResult`,
`HorizonConfiguration`, `canonical_weeks`,
`phase_monthly_series_calendar_day_overlap_v1`,
`reconcile_explicit_weekly_schedule`,
`phase_monthly_series_explicit_override`,
`phase_model_input_plan_calendar_day_overlap_v1`,
`phase_monetary_plan_calendar_day_overlap_v1`); new
`ancestry_mmm/tests/test_phasing.py` (26 tests); `core/planning/__init__.py`
re-exports; `REQ-SCEN-002.md`/`REQ-SCEN-003.md` and
`docs/specification_authority.md` updated to reflect implementation;
`index.json` required_tests extended. No schema, migration, or
persisted-field changes - this module is framework-independent and not yet
called from any application service. mypy: 241 unchanged (`core/planning`
is the mypy-blocked path; the new module type-checks clean).
**Owner:** Data Science / Platform engineering.
**Status:** Core phasing and horizon-configuration contracts implemented
and tested. Future-context builder and all application-layer wiring
(`application/scenario_service.py`, `pages/08_Scenario_Planner.py`,
`core.optimization`'s objective, `core.sequential_simulation.WeeklyPlan`
construction from a phased result) remain separately-scoped, not attempted
in this targeted work package.

## Post-PR262 correctness, authority, and release-gate hardening (Work Package 2)

**Date:** 2026-08-17
**Decision:** Before building the application-level sequential planner
(`Media-Mix-Lab: Coding LLM Next Steps Post PR262`), fix the authority-doc
and release-gate defects that PR #262's review surfaced rather than build
on top of them:

1. `REQ-SCEN-002.md`'s own top-of-file "Approval and traceability" section
   still said the phasing contract was "Not yet implemented" and cited a
   stale "WP6" label, directly contradicting its own "Owner and status"
   section a few dozen lines below, which correctly said WP1 implemented
   it. Fixed - the top section now states the implemented status and cites
   PR #262.
2. `REPO_REVIEW_AND_NEXT_STEPS.md`'s "Current `main` reviewed: `<SHA>`"
   field is structurally guaranteed to go stale: a branch cannot know the
   future squash-merge commit SHA that will become `main`, and this
   happened in practice (the field named PR #261's merge commit while
   PR #262 was already merged on top of it). Replaced with a "Repository
   state through merged PR #<N>" milestone marker; the previously-existing
   anti-drift test that enforced the old convention
   (`test_repo_review_current_sha_is_well_formed_and_historical_shas_are_labelled`)
   is replaced with one that forbids the "current main" field pattern from
   reappearing (`test_repo_review_does_not_use_a_necessarily_drifting_current_main_field`)
   plus one that still requires every mentioned SHA to be explicitly
   labelled historical/superseded/a specific merge commit
   (`test_repo_review_historical_shas_are_labelled`).
3. `REQ-STATE-001`/`REQ-SCEN-001` described `simulate_sequential_outcomes_
   posterior`'s "full per-draw posterior paths" without distinguishing
   that it varies each draw's own decay/Hill parameters through the future
   recursion but reuses one fixed, caller-supplied `SequentialCarryInState`
   across every draw - historical starting-adstock uncertainty is not
   propagated. Tightened both records' wording and "Not yet covered"
   sections to name this gap and the related gap that no market-specific
   (Model C) equivalent of this posterior helper exists yet - both remain
   real, not-yet-implemented capabilities for Work Package 3.
4. GitHub issue #123 said the mypy debt ratchet was 245; the authoritative
   `.mypy-baseline-count` file has read 241 since Work Package 4/5 of the
   prior brief. Updated the issue to 241 and pointed it at
   `.mypy-baseline-count` as the authoritative source, to prevent the
   two from silently disagreeing again.
5. `core/planning/phasing.py` hardening: an explicit weekly schedule key
   outside the canonical calendar was silently ignored (the reconciliation
   loop only ever read canonical week labels via `.get(label, 0.0)`, never
   validating the schedule's own keys) rather than rejected -
   `_validate_weekly_schedule` now requires every key be canonical and
   every value finite and non-negative. `WeeklyAllocationResult` validated
   its `period_labels`/`values` length match but not the values themselves
   - `__post_init__` now defensively rejects non-finite/negative values
   even on direct construction, not only via the module's own governed
   functions. The monetary path's scalar cost-mapping call reshaped the
   mapping's return value and silently took only the first element,
   discarding any extra values a malformed/custom mapping might return -
   it now fails closed (`PhasingReconciliationError`) unless the mapping
   returns exactly one finite, non-negative value. Added numerical-
   equivalence coverage (`test_phasing_calendar_overlap_equivalence.py`)
   between this module's day-overlap arithmetic and
   `core.frequency_conversion`'s independently-governed
   `calendar_overlap_allocation` day-overlap arithmetic across leap
   February, a 30-day month, a 31-day month, a shared boundary week, a
   narrow/partial calendar, and consecutive tracked months - the two
   remain deliberately separate governance objects/method IDs (different
   requirement records, forward-planning vs. backward-conversion), this
   only guards the shared arithmetic principle from silently drifting.
6. `scripts/wait_for_pr_green_then_merge.ps1` hardening: added a remote/
   auth preflight (verifies the `origin` remote matches the expected repo,
   fetches it, verifies `gh` authentication, and clears a stale invalid
   `GITHUB_TOKEN`/`GH_TOKEN` environment override that shadows a working
   keyring login rather than failing outright - this exact failure mode
   was hit live while preparing this package); captures the PR's exact
   head SHA once, before any waiting, and re-verifies it is unchanged
   immediately before merging, using `gh pr merge --match-head-commit` as
   a second, server-side guard against a race where new commits land
   after checks were observed green; fails closed on any CI check name
   not explicitly classified as required, allowed-skipped, or
   informational, rather than silently ignoring a newly-added job; and
   automatically detects whether the PR's diff touches a Candidate A
   model-mathematics file (the same file list
   `candidate-a-recovery-gate-check` annotates, kept in sync by a
   cross-checking test) and dispatches the schedule/manual-only
   `candidate-a-recovery` job itself via `gh workflow run
   --ref <branch>` rather than depending on the caller remembering
   `-RequireCandidateARecovery`. The unsafe post-merge-verification bypass
   was renamed from `-SkipMainVerification` to
   `-DangerouslySkipMainVerification` (unchanged behaviour, harder to
   reach for by habit) and now prints an explicit warning naming the
   contract it breaks ("green PR -> merge -> green main -> next work
   package") - the autonomous work-package loop must never pass it.
   `test_merge_gate_script_contract.py` adds static contract coverage
   (plus a live Windows-PowerShell-5.1 parse check when a `pwsh`/
   `powershell` binary is available) for each of these properties, since
   this repository has no Pester tooling and the Python test jobs run on
   `ubuntu-latest`.

**Alternatives considered:** Leaving `REQ-STATE-001`/`REQ-SCEN-001`'s
wording as "implemented" without qualification (rejected - `AGENTS.md`'s
authority hierarchy requires authority records not overstate posterior
completeness; Work Package 3 depends on this gap being named precisely, not
rediscovered). Deleting the old "current main SHA" anti-drift test outright
instead of replacing it with an equivalent-strength test for the new
convention (rejected - the brief requires an anti-drift test for whichever
convention is chosen, not merely removing the old one). Merging
`core.planning.phasing`'s day-overlap arithmetic with
`core.frequency_conversion`'s into one shared function (rejected, per the
brief - the two remain intentionally separately governed; only numerical
equivalence coverage was added, not a shared code path).
**Impact:** `docs/approved_requirements/REQ-SCEN-002.md`,
`docs/approved_requirements/REQ-STATE-001.md`,
`docs/approved_requirements/REQ-SCEN-001.md`,
`REPO_REVIEW_AND_NEXT_STEPS.md` updated; `ancestry_mmm/core/planning/
phasing.py` hardened (no new public contract, only stricter validation on
the existing one); `ancestry_mmm/tests/test_phasing.py` extended; new
`ancestry_mmm/tests/test_phasing_calendar_overlap_equivalence.py`; new
`ancestry_mmm/tests/test_merge_gate_script_contract.py`;
`ancestry_mmm/tests/test_repository_status_conformance.py`'s SHA-drift test
replaced; `scripts/wait_for_pr_green_then_merge.ps1` hardened; GitHub issue
#123 updated. No schema, migration, or persisted-field changes. mypy: 241
unchanged (no core/application code outside `core/planning/phasing.py`
touched, and that module already type-checked clean).
**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.

## Draw-consistent sequential state and evaluation context (Work Package 3)

**Date:** 2026-08-17
**Decision:** Harden the sequential engine for application-level
uncertainty and candidate/reference correctness (`Media-Mix-Lab: Coding
LLM Next Steps Post PR262`), closing three gaps Work Package 2's authority
review named precisely rather than glossed over:

1. **Draw-consistent posterior evaluation.** `simulate_sequential_
   outcomes_posterior` (existing, WP5) receives one fixed `carry_in`,
   reused for every posterior draw - only future-recursion parameters vary
   by draw, so historical starting-adstock uncertainty is not propagated.
   Added `simulate_sequential_outcomes_posterior_draw_consistent`: for
   each selected draw, extract that draw's own parameters via the
   existing `extract_posterior_params`, reconstruct
   `SequentialCarryInState` from the historical frame using those same
   parameters (`reconstruct_starting_state` already accepted per-draw
   `FHPosteriorParams` - the missing piece was the per-draw caller loop
   around it, not new carry-in mathematics), then evaluate the future
   plan. Proven against the batch replay (`predict_mu`) per individual
   draw, not merely at the posterior mean - including a market that is
   not first in the fit's market list.
2. **Model C posterior parity.** Model C had full deterministic sequential
   replay (`simulate_sequential_outcomes_market_specific`,
   `reconstruct_starting_state_market_specific`) but no high-level
   draw-level posterior-array wrapper at all. Added
   `simulate_sequential_outcomes_posterior_market_specific` (fixed-
   carry-in parity with the existing Model A function) and
   `simulate_sequential_outcomes_posterior_market_specific_draw_consistent`
   (draw-consistent parity), both proven the same way as their Model A
   counterparts.
3. **Historical-state safety.** `reconstruct_starting_state`'s market-block
   lookup (`historical_frame["market_bounds"][meta.markets.index(market)]`)
   was unchecked: a too-short `market_bounds` raised an unhelpful
   `IndexError`, an out-of-range bound silently read past `X_media`, and -
   the genuinely dangerous case - a `market_bounds`/`market_idx`
   disagreement would silently reconstruct carry-in from a different
   market's history with no error at all. `_resolve_and_validate_market_
   history` now validates all three explicitly and raises a specific,
   actionable `ValueError` for each failure mode, shared by both Model A
   and Model C reconstruction.
4. **Shared sequential evaluation context.** `compute_incremental_outcome`
   can only check market/period/outcome identity between two results - it
   cannot see whether a candidate and reference were actually evaluated
   with the same model/posterior/historical-state/phasing/future-
   assumption/cost/counterfactual-policy identity, leaving "same non-
   decision assumptions" a caller-trust convention rather than an
   enforced one. New `core/sequential_evaluation_context.py`:
   `SequentialEvaluationContext` (ten required identity/fingerprint
   fields - deliberately strings, not deep objects, since the phasing/
   future-context/cost-mapping application services those identities will
   eventually come from do not exist yet, per `REQ-SCEN-002`'s own "Not
   yet covered" boundary), `require_matching_context` (raises unless a
   caller explicitly names which field is allowed to differ - e.g. a
   deliberately varied cost assumption), and
   `compute_incremental_outcome_with_context` (the existing function,
   guarded).

Also added: a regression fixture proving draw-specific historical carry-in
genuinely changes early-horizon output when decay varies meaningfully
between draws, and specifically proving `simulate_sequential_outcomes_
posterior_draw_consistent`'s output for one draw differs from what a
"reused a fixed carry-in across draws" implementation would produce -
protecting the draw-consistency property itself against a future
refactor, not just its current correctness.

**Alternatives considered:** Building the draw-consistent evaluator as new
carry-in mathematics (rejected - `reconstruct_starting_state` already
accepted per-draw parameters; the gap was purely the missing per-draw
caller loop, and inventing a second carry-in reconstruction path would
duplicate already-tested code for no reason). Making
`SequentialEvaluationContext` hold references to the actual phasing/
future-context/cost-mapping objects instead of identity strings (rejected
- those application-layer services do not exist yet; a context module
that imports them now would either invent their shape prematurely or
create a circular/forward dependency on not-yet-built code - identity
strings let each service supply its own stable identity once it exists,
without this module needing to know its internal shape). Silently
tolerating a `market_bounds`/`market_idx` mismatch as "caller error, not
our problem" (rejected - AGENTS.md's fail-closed principle and this
specific gap's blast radius, silently leaking another market's history
into a carry-in reconstruction, make this exactly the kind of defect that
must raise rather than warn).
**Impact:** `ancestry_mmm/core/sequential_simulation.py` (three new public
functions, `_resolve_and_validate_market_history`, updated `__all__`); new
`ancestry_mmm/core/sequential_evaluation_context.py`; new
`ancestry_mmm/tests/test_sequential_evaluation_context.py`;
`ancestry_mmm/tests/test_sequential_simulation.py` extended (four new test
classes: draw-consistent posterior, Model C parity, early-horizon
regression, historical-state safety); `docs/approved_requirements/
REQ-STATE-001.md`/`REQ-SCEN-001.md` updated to describe the new
capabilities precisely, replacing the "not yet covered" gaps Work Package
2 named. No schema, migration, or persisted-field changes - this remains a
framework-independent core-module addition, not yet called from any
application service. mypy: 241 unchanged (new module type-checks clean).
**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.

## Future context, governed WeeklyPlan construction, and terminal incremental response (Work Package 4)

**Date:** 2026-08-17
**Decision:** Build the bridge from phased monthly decisions plus explicit
future assumptions to an application-safe weekly simulation input
(`Media-Mix-Lab: Coding LLM Next Steps Post PR262`), three new
framework-independent `core/planning/` modules:

1. **`future_context.py`** - continues the fitted model's own trend and
   Fourier/seasonality definitions into future weeks, rather than
   inventing a new one. Research finding before writing any code: trend is
   defined in `data.preprocessor.prepare_fh_modeling_frame` as a
   per-market row-position index normalized by that market's own
   historical row count (`arange(n) / max(n - 1, 1)`) - not date-derived,
   no shared origin across markets - while Fourier/seasonality
   (`create_fourier_features_from_calendar`) is already a pure function of
   calendar date (day-of-year, `period_days=365.25`) with no historical-
   length dependency, so it generalises to future dates unchanged.
   `continue_trend` extends the SAME trend formula forward at future row
   positions (never reset to zero, never held flat - the existing
   Scenario Planner's steady-state approximation holds trend flat at the
   last historical value, explicitly documented there as "a planning
   approximation, not a forecast"; this module's contract requires the
   real continuation instead). `continue_fourier` reproduces the same
   calendar-anchored formula. Neither function *imports*
   `data.preprocessor` - that module already imports from `core`
   (`core.schema`, `core.outcomes`), so `core` importing back from `data`
   would be a circular/layering-inverted dependency (confirmed by an
   actual `ImportError` when first wired into `core/planning/__init__.py`
   - see point 4 below). Both formulas are mirrored instead, kept
   numerically identical by test. Promotions/events always require an
   explicit future value in every mode (no relaxation); exogenous controls
   require an explicit future value in official mode (fail closed if
   absent) or may use an explicitly opted-in, explicitly eligible
   `hold_last_observed` assumption in exploratory mode only - recorded
   per-control and excluded from decision-ready status.
2. **`weekly_plan_builder.py`** - the governed construction boundary above
   phased allocations (`core.planning.phasing.WeeklyAllocationResult`/
   `WeeklyModelInputDerivation`) and a `FutureContextResult`: validates
   exact canonical week order, an exact expected channel set (an unknown
   extra channel previously would have been silently ignored by
   `WeeklyPlan.to_media_matrix`, which only raises for a *missing*
   channel), finite non-negative allocation values even on a directly-
   constructed allocation, and Fourier/outcome/control shape and identity
   against the fitted model - before constructing `core.sequential_
   simulation.WeeklyPlan`. Stores construction provenance/fingerprint.
   Deliberately does not duplicate `application.scenario_service.
   ScenarioPlan` (the steady-state method's own input type).
3. **`terminal_response.py`** - the business-facing terminal candidate/
   reference evaluator the prior authority review (Work Package 2) named
   as missing: `core.sequential_simulation.zero_media_extension_plan` is a
   low-level decay fixture (zero future media AND zero promo/trend/
   Fourier/controls), correct for isolating pure adstock decay in a unit
   test but not a business terminal-response definition. This module
   extends candidate and reference over the SAME future calendar sharing
   ONE real future non-decision context (trend/seasonality/controls/
   promotions, never zeroed), zero future decision media only (the
   initial residual-carryover policy), and reports `candidate - reference`
   as a structurally separate, typed `TerminalIncrementalResult` - never
   folded into a plan-window result or an optimisation objective.
4. **Circular-import fix.** Initially wired `weekly_plan_builder`/
   `terminal_response` into `core/planning/__init__.py`'s top-level
   re-exports (matching `phasing.py`'s own precedent) - this produced a
   real `ImportError` (`cannot import name 'DEFAULT_N_DRAWS' from
   partially initialized module 'ancestry_mmm.core.uncertainty'`), because
   `core.sequential_simulation` itself imports `core.planning.value`,
   which triggers `core/planning/__init__.py` to execute first; that
   `__init__.py` importing `terminal_response`, which imports
   `core.sequential_simulation` back, completed the cycle. Fixed by
   importing `weekly_plan_builder`/`terminal_response` directly from their
   submodule paths (not re-exported from the package `__init__`) -
   `future_context.py` has no such dependency and remains re-exported.
   Caught before merge by the exact `Compile + Import` CI job's own
   `import ancestry_mmm.core.optimization` check, reproduced locally
   first.

**Alternatives considered:** Holding trend flat at the last historical
value for the future window, matching the existing Scenario Planner's
steady-state approximation (rejected - REQ-SCEN-002 requires the future
context be "generated deterministically... using the same model
definition the fitted model used," and that existing approximation is
itself explicitly documented as a steady-state-only compromise, not a
contract this genuinely sequential future-context builder should inherit).
Importing `create_fourier_features_from_calendar`/the trend formula
directly from `data.preprocessor` (rejected - real circular import, `data`
already depends on `core`; mirrored with equivalence tests instead,
matching this repository's existing precedent for `core.planning.phasing`
vs. `core.frequency_conversion`'s day-overlap arithmetic). Allowing
promotions to use `hold_last_observed` in exploratory mode, symmetric with
exogenous controls (rejected - REQ-SCEN-002's text scopes that relaxation
to "future exogenous controls" only; promotions/events require an explicit
planned value or approved event schedule in every mode).
**Impact:** New `ancestry_mmm/core/planning/future_context.py`,
`weekly_plan_builder.py`, `terminal_response.py`; `core/planning/__init__.py`
re-exports extended (`future_context` only, see point 4 above) and its
module-layout docstring updated to explain the two modules deliberately
not re-exported; new `ancestry_mmm/tests/test_future_context.py`,
`test_weekly_plan_builder.py`, `test_terminal_response.py`; `docs/
approved_requirements/REQ-SCEN-002.md`/`REQ-SCEN-003.md` and
`docs/specification_authority.md` updated to reflect implementation;
`REPO_REVIEW_AND_NEXT_STEPS.md` baseline bumped to PR #264 and "Delivered
foundation"/"Known bounded gaps" updated. No schema, migration, or
persisted-field changes - these remain framework-independent core modules,
not yet called from any application service (Work Package 5). mypy: 241
unchanged (one new error surfaced and fixed during development - a
parameter-name shadowing issue in `future_context.py` that widened a
local variable's inferred type back to its declared parameter type after
reassignment; renamed the local instead of reusing the parameter name).
**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.

## Sequential scenario evaluation service (Work Package 5, part 1)

**Date:** 2026-08-17
**Decision:** `Media-Mix-Lab: Coding LLM Next Steps Post PR262`'s Work
Package 5 brief covers both an application-service evaluation layer
(§11.1-11.3, most of §11.5-11.7) and Streamlit UI integration (§11.4, the
remainder of §11.5-11.7 - a method toggle, a real-browser lifecycle test).
Split into two coherent slices rather than one combined PR, mirroring this
repository's own established pattern (recorded against Candidate A:
"WP1/WP2/WP3 each delivered one coherent slice... rather than one combined
PR"). This package is the first slice: the core evaluation service,
governance-reuse, and full test coverage below - genuinely mergeable and
valuable on its own. The Streamlit page/browser-test slice is a focused,
explicitly-tracked follow-up (see `REPO_REVIEW_AND_NEXT_STEPS.md`'s
updated "Known bounded gaps").

Delivered:

1. **`core/sequential_scenario_evaluation.py`**:
   `evaluate_manual_scenario_sequential` orchestrates an already-governed
   candidate/reference `WeeklyPlan` pair (built by the caller via
   `core.planning.weekly_plan_builder.build_governed_weekly_plan`) through:
   shared historical-state reconstruction (one carry-in for both candidate
   and reference, per `REQ-SCEN-001` item 1), evaluation through
   `core.sequential_evaluation_context.compute_incremental_outcome_with_context`
   (both sides pass the *same* context object, structurally guaranteeing
   identical non-decision identity), monthly aggregation by summing
   already-computed weekly rows (never an independent monthly
   recalculation), configured short/long horizon summation
   (`HorizonConfiguration`'s own inclusive-bounds convention), optional
   terminal incremental response (`core.planning.terminal_response`,
   structurally separate field, never merged into the plan-window result),
   optional fully draw-consistent posterior evaluation
   (`simulate_sequential_outcomes_posterior[_market_specific]_draw_consistent`,
   WP3), and economics coverage via `core.scenario_governance.
   resolve_scenario_plan` (confirmed period-key-agnostic - works unchanged
   against weekly period labels, no fork needed).
2. **Governance reuse, not reimplementation.** Official-mode governance
   resolution calls the exact same `core.planning_governance.
   resolve_planning_governance` and builds the same
   `core.planning.value.ScenarioGovernanceDependencies` shape
   `core.optimization.evaluate_manual_scenario` (the steady-state path)
   uses - the only difference is stamping `SEQUENTIAL_WEEKLY_PLANNING_
   EVALUATION_SEMANTICS` instead of `CURRENT_PLANNING_EVALUATION_
   SEMANTICS`. The two evaluation methods can never disagree about what
   "official" governance means, because they resolve it through the same
   code.
3. **New result type, not a stretched one.** `SequentialScenarioEvaluationResult`
   is deliberately separate from `core.planning.value.
   ScenarioEvaluationResult` - that type's `predicted: pd.DataFrame` field
   is a monthly-wide-table shape (and the existing scenario-persistence
   CSV convention assumes it), which does not fit a weekly/terminal/
   posterior-draw result. Not a competing planning domain - a distinct
   result shape for a distinct calculation grain, exactly the boundary
   `core.planning.weekly_plan_builder`'s own docstring already drew
   against `ScenarioPlan`.
4. **`validate_scenario_dependencies`'s staleness check fixed to be
   engine-aware.** Research before writing any code found this real,
   pre-existing latent bug: the `planning_semantics_fingerprint` staleness
   comparison (`core/optimization.py`, added by PR 88B) was hard-coded to
   compare only against `CURRENT_PLANNING_EVALUATION_SEMANTICS.fingerprint()`
   - a schema-4 scenario evaluated under any other engine's semantics
   would always read `stale`, forever, even with nothing else changed. The
   comment already sitting above that check had anticipated this exact
   gap ("a future sequential engine... is stale") without it ever being
   implemented as engine-aware. Fixed with a
   `_CURRENT_PLANNING_SEMANTICS_FINGERPRINTS` frozenset covering every
   currently-approved engine's semantics fingerprint - extend it, never
   shrink it, when a further evaluation engine is approved. Required
   exporting `SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS` from
   `core.planning`'s package `__init__` (previously private to
   `core.planning.value`, unused anywhere in the application).
5. **`application/scenario_service.py`**: `SequentialManualScenarioInput`
   and `ScenarioService.evaluate_manual_sequential` added, mirroring
   `evaluate_manual`'s exact dispatch shape (validate required fields,
   local-import the core function, `try`/`except Exception` wrapping) -
   confirmed by research to be this module's own established pattern for
   adding a new evaluation path, not a deviation from it.
6. **Candidate A boundary inherited for free**, confirmed by research
   before implementation: `simulate_sequential_outcomes[_market_specific]`
   already raises `CandidateAReplayNotSupportedError` for a Candidate A
   fit (mirroring `core.predict.predict_mu`'s existing WP3 guard) - calling
   into those functions means this new evaluation path fails closed with
   no additional gate required.

**Alternatives considered:** Branching inside `core.optimization.
evaluate_manual_scenario`/`ScenarioService.evaluate_manual` for the
sequential case (rejected - the existing dispatch-pattern precedent, and
this repository's "do not create a second incompatible planning domain"
instruction, both point to a parallel function/method calling a different
core module, not a branch inside the steady-state one). Coercing sequential
output into `ScenarioEvaluationResult.predicted`'s monthly-wide-table shape
to avoid a new result type (rejected - would either lose the weekly/
terminal/posterior-draw detail the sequential contract exists to provide,
or silently misuse a field whose shape assumes monthly grain). Delivering
the Streamlit page integration in the same PR (rejected - genuinely a
much larger, qualitatively different diff requiring visual verification in
a running app; splitting into two coherent slices matches this
repository's own established multi-PR pattern and keeps this package
independently reviewable and mergeable).
**Impact:** New `ancestry_mmm/core/sequential_scenario_evaluation.py`;
`ancestry_mmm/application/scenario_service.py` extended
(`SequentialManualScenarioInput`, `evaluate_manual_sequential`,
`ScenarioServiceResult.sequential_evaluation`); `ancestry_mmm/core/
optimization.py`'s `validate_scenario_dependencies` fixed (engine-aware
semantics comparison); `ancestry_mmm/core/planning/__init__.py` re-exports
`SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS`; new
`ancestry_mmm/tests/test_sequential_scenario_evaluation.py`,
`test_scenario_service_sequential.py`; `ancestry_mmm/tests/
test_g2a7a4_scenario_governance_persistence.py` extended with the
engine-aware staleness regression; `docs/approved_requirements/
REQ-SCEN-001.md`/`REQ-SCEN-002.md`/`REQ-SCEN-003.md` and
`docs/specification_authority.md` updated;
`REPO_REVIEW_AND_NEXT_STEPS.md` baseline bumped to PR #265, "Delivered
foundation"/"Known bounded gaps" updated. No schema, migration, or
persisted-field changes - a saved sequential scenario's persistence
format does not exist yet (remains part of the UI-integration follow-up).
mypy: 241 unchanged (new module type-checks clean; the blocking
`core/planning` + `core/validation_policy.py` + `application` mypy scope
also remains clean). Real UK end-to-end data validation: DEFERRED pending
authorised source-data availability (unaffected by this package).
**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate. Streamlit UI integration is Work Package 5, part
2 - not started.

## Sequential scenario planner UI wiring (Work Package 5, part 2)

**Date:** 2026-08-17
**Decision:** Wire `core.sequential_scenario_evaluation`/`ScenarioService.
evaluate_manual_sequential` (Work Package 5, part 1) into
`pages/08_Scenario_Planner.py`'s manual "Edited plan and calculated
result" tab, per `Media-Mix-Lab: Coding LLM Next Steps Post PR262` §11.4.
A "Manual plan evaluation method" radio (steady-state monthly / sequential
weekly) is the single source of truth for the rerun, mirroring the
existing `governance_mode` radio's own pattern - never inferred, never
silently switched. Only the manual tab; the constrained and unconstrained-
benchmark optimiser tabs remain steady-state-only (a separate,
not-yet-approved follow-up, consistent with WP5 part 1's own scope split).

Delivered:

1. **Plan window always continues history with no gap.**
   `_sequential_plan_start_week` returns the Monday immediately following
   the market's last historical canonical week - never the steady-state
   tab's user-chosen "Plan start month" - to avoid an unmodelled gap or
   double-counted overlap between historical carry-in and the first
   planned week.
2. **Reused inputs, not a parallel plan representation.** The sequential
   tab reuses the existing monthly spend-plan grid, activity/counterfactual/
   cost-mapping/objective/value-mapping/currency-context state unchanged -
   only re-seating the analyst's *ordered* monthly values onto real
   calendar months starting at the continuation point (order preserved,
   labels replaced). The reference/counterfactual plan is resolved via the
   existing `core.scenario_governance.resolve_counterfactual` at monthly
   grain first, then re-seated identically to the candidate - reusing the
   steady-state path's own governance resolution rather than inventing a
   sequential-specific one.
3. **A genuinely partial first month cannot be phased through
   `calendar_day_overlap_v1` unmodified - a real defect found and fixed
   during this package, not merely a design choice.** Because the plan
   window starts mid-month (point 1), the first sequential month's
   covered days are a strict subset of the real calendar month, but
   `REQ-SCEN-002`'s governed phasing function requires its `calendar` to
   *fully* cover every month it phases (reconciliation checks
   `allocated_total == value` against the month's *full* day count,
   regardless of how much of that month the calendar's weeks actually
   span). The first implementation pro-rated the first month's value by
   `covered_days / days_in_month` and fed it through the governed function
   using a `calendar` truncated to start at the plan's continuation week -
   this reconciled but the phasing function *also* computed the same
   `covered_days / days_in_month` day-overlap ratio internally (since its
   `source_days` is always the real month's full length), silently
   squaring the intended pro-ration (a 76.1 vs 7.61 - 10x - mismatch caught
   by a new `test_scenario_planner_apptest.py` case exercising the
   sequential tab, not by manual review). Fixed by phasing the first
   month's value directly: a small page-local helper
   (`_first_month_fragment_schedule`) applies the same day-overlap formula
   `calendar_day_overlap_v1` itself uses, but scoped to `[plan_start_week,
   first_month_end]` (the covered days only) rather than the month's full
   calendar bounds, and every subsequent whole month is phased through the
   *unmodified* governed function, calendar unchanged - the two
   contributions are summed per week (never chosen between), since a
   boundary week between month 1 and month 2 legitimately carries spend
   from both. `core/planning/phasing.py` itself is not modified; this
   composition lives entirely in the page.
4. **Future context and decision-readiness.** Official mode unless the fit
   has exogenous controls, in which case exploratory `hold_last_observed`
   (held at each control's last observed value) with an explicit
   not-decision-ready warning - matching `REQ-SCEN-002`'s official/
   exploratory control-continuation contract exactly, reusing
   `core.planning.future_context.build_future_context` unchanged.
5. **Rendered output.** Weekly and monthly incremental outcome tables
   (monthly summed from weekly, never independently recalculated -
   `REQ-SCEN-001` item 6), short/long response-horizon metrics, and
   provenance fingerprints via the existing `render_technical_details`
   pattern. Explicit captions disclose that terminal incremental
   carryover, posterior uncertainty, and scenario saving are not yet
   available for this method in this UI - never silently absent.
6. **A second, real pre-existing bug found and fixed in the same package:**
   the counterfactual resolution call passed `activity_definitions`
   (the session-state list, `[]` when no activities are configured) to
   `resolve_counterfactual` directly, instead of `activity_definitions or
   None` (the pattern used everywhere else on this page). Since
   `resolve_counterfactual` treats a non-`None` `activity_definitions` as
   "every model-input column must have a matching activity definition,"
   the empty-list default made a sequential evaluation with no configured
   activities fail with "missing activity definition for model input" -
   caught by the same new AppTest case before it reached a real user.

**Alternatives considered:** Anchoring the sequential plan window to a
real calendar-month boundary instead of the historical-continuation Monday
(rejected - breaks the "continue the exact same weekly cadence with no
gap" contract WP5 part 1's own kernel-level invariants assume, and would
either duplicate or contradict history for the days between the month
start and the actual continuation point). Extending the phasing
`calendar` back to the first day of the first month so
`calendar_day_overlap_v1` sees a "whole" month, then discarding the
weeks before the continuation point after the fact (rejected - `canonical_
weeks` anchors its 7-day cadence to `calendar.start`, so a month-aligned
calendar start generates a *different* weekly grid than one anchored to
the continuation Monday, breaking cadence continuity for every week, not
just the first). Using `phasing.py`'s explicit-weekly-schedule override
(`reconcile_explicit_weekly_schedule`) for the whole plan (considered and
rejected after working through the arithmetic - its per-week
tracked-month weighting reconstructs each month's share by that week's
*relative* day-overlap among tracked months sharing it, which does not
generally equal `calendar_day_overlap_v1`'s own per-month-normalized
contribution at a boundary week once one of the two months uses a
different (covered-days, not full-days) normalizer - correct only for the
single-tracked-month-per-week case, not the general one this plan window
needs). Modifying `core.planning.phasing` itself to accept a partial first
month (rejected for this package - `phasing.py` is a shared,
requirements-governed module already merged and tested under WP1; the
page-local day-overlap-fragment-plus-governed-function composition
achieves the identical numerical result without changing its contract or
blast radius, and remains available as a future refactor if a second
caller needs the same partial-month case).
**Impact:** `ancestry_mmm/pages/08_Scenario_Planner.py` extended (method
radio, `_sequential_plan_start_week`, `_prorated_sequential_monthly_
values`, `_first_month_fragment_schedule`, `_evaluate_sequential_manual_
plan`, `_render_sequential_manual_tab`, `_render_steady_state_manual_tab`
- the pre-existing steady-state tab body converted to a same-indentation
function rather than re-indented, a deliberate minimal-diff choice);
`ancestry_mmm/tests/test_scenario_planner_apptest.py` extended with two
new cases (sequential tab renders its own content without exception; the
default method stays steady-state) and one existing invariant count
(`**scenario_governance_kwargs`) updated from 4 to 5 for the new call
site; `docs/approved_requirements/REQ-SCEN-001.md`/`REQ-SCEN-002.md`/
`REQ-SCEN-003.md`/`REQ-STATE-001.md` and `docs/specification_authority.md`
updated to reflect UI implementation (and, for `REQ-SCEN-001.md`, a
pre-existing inconsistency between its own inline "implemented" item
annotations and its stale "Owner and status" footer, corrected in
passing); `REPO_REVIEW_AND_NEXT_STEPS.md` baseline bumped to PR #267
(also correcting WP5 part 1's own entry, which had bumped it to #265
instead of its actual PR #266), "Delivered foundation"/"Known bounded
gaps" updated. No schema, migration, or persisted-field changes - saving a
sequential scenario remains out of scope for this UI. mypy: `core`
ratchet unchanged at 241; the three always-zero-tolerance scopes
(`core/planning`, `core/validation_policy.py`, `application`) remain
clean; `pages/` is outside the mypy CI gate.
**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.


## PRD authority reconciliation: Bayesian validation, causal identification, calibration and forecast-risk overlay (Work Package 0)

**Context:** The task-specific implementation brief `Media-Mix-Lab: Coding
LLM Next Steps After PR #267 and Latest PRD Validation Updates`
(2026-08-17) supplied five newer focused PRD revisions - Part 3 v1.7
(Bayesian validation and experiment calibration), Part 6 v1.6 (estimand-
specific causal identification, latent-state identification, structural
stability, experiment calibration), Part 7 v1.5 (uncertainty-aware
predictive validation, leakage-safe historical validation, structural
stability, identification, calibration, downstream forecast consequence),
Part 9 v1.5 (reporting requirements for those evidence types), and Part 10
v1.6 (UX requirements for those evidence types) - none of which had yet
been reconciled into `docs/specification_authority.md` or
`docs/approved_requirements/`. The five source documents were supplied as
local, untracked files under `docs/PRD/` on a separate, unrelated stale
checkout (`agent/ux-refinement-pr6`, forked around PR #178-181); they have
never been committed to this repository in any branch (consistent with how
RFP/vendor PRD material has always been kept local-only, not version
controlled) and were read in place rather than copied into this branch.

**Decision:** Reconciled the five parts' implementation-ready invariants
into eight new scoped approved requirement records - `REQ-LEAK-001`
(leakage-safe/time-respecting historical validation folds), `REQ-STAB-001`
(structural stability evidence across time-respecting folds), `REQ-PPD-001`
(posterior predictive metric distributions, distinct from point/outcome-PI
metrics), `REQ-IDENT-001` (estimand-specific graphical identification -
backdoor paths/adjustment sets, distinct from `REQ-GRAPH-001`'s existing
structural graph validation and `core.identification_diagnostics`'s existing
correlation/condition-number checks), `REQ-LATENT-001` (latent-state scale/
location identification, with Candidate A's latent branded-search demand as
the first concrete integration target per the brief), `REQ-EXPMODE-001`
(experiment evidence modes and provenance - `validation_only`/
`prior_calibration`/`likelihood_calibration`/`diagnostic_comparison`),
`REQ-CALIB-001` (calibrated-versus-uncalibrated model comparison), and
`REQ-FORECAST-001` (downstream forecast-consequence evidence, narrower than
the still-unapproved future-assumption-bundle scope). All eight are
target-state contracts only - zero implementation exists yet for any of
them; each record's own "Capability status" says so explicitly.

Each record explicitly excludes the specific numeric thresholds, formulas,
and business/UX label decisions that the source PRD parts themselves leave
as open decision-required items in their own internal registers (Part 6 S37
`MD-001`-`MD-021`; Part 7 S48 `VL-001`-`VL-027`; Part 9 S48
`RP-001`-`RP-025`; Part 10 S47 `UX-001`-`UX-030` - roughly 100 individually
numbered open items across the four registers). None of those items is
approved by this reconciliation; each remains decision-required and must not
be hard-coded from PRD prose in a future work package without a separate
decision record, per the brief's own instruction not to "invent blocking
thresholds or a likelihood-calibration formula."

`docs/specification_authority.md` gained a new "Version history: focused
Bayesian validation, causal identification, calibration and forecast-risk
overlay" section with a five-part per-part version table (superseding the
prior narrower Part 3 v1.6 variable-coverage overlay's version label only -
that overlay's approved capability, `REQ-COVERAGE-001`, is unaffected), and
eight new rows in the "Current implementation gaps" table (all classified
"Requirement exists but capability incomplete", the established state for
an approved record with zero-to-partial implementation, distinct from "no
approved requirement/decision yet"). The pre-existing "Experiment
translation and recalibration" gap row is superseded by the two new
experiment-related rows rather than left as a contradictory duplicate.

**Rejected alternative:** Converting the ~100 VL-*/RP-*/UX-*/MD-* items into
100 individual new decision-log or `docs/approved_requirements/` entries
(rejected - the source PRD parts already maintain these as their own
numbered, versioned registers; duplicating them here would create a second,
divergent copy that could drift from the source on the next PRD revision.
Each new `REQ-*` record instead cites the specific register IDs it defers
to, by number, so a future reconciliation can locate them without
re-deriving the full list).

**Impact:** `docs/approved_requirements/REQ-LEAK-001.md`,
`REQ-STAB-001.md`, `REQ-PPD-001.md`, `REQ-IDENT-001.md`,
`REQ-LATENT-001.md`, `REQ-EXPMODE-001.md`, `REQ-CALIB-001.md`,
`REQ-FORECAST-001.md` (new); `docs/approved_requirements/index.json` (eight
new entries, `generated_at` bumped to 2026-08-17); `docs/specification_
authority.md` (new overlay section, eight new/updated gaps-table rows);
`ancestry_mmm/tests/test_outcome_approval.py` (new anti-drift tests guarding
the new overlay table and the eight new records' gap-table classification).
No core module, schema, or persisted artefact changes - this Work Package
is documentation/governance reconciliation only, per its own scope
("translate implementation-ready invariants into scoped approved
requirement records ... leave genuinely unresolved statistical methods/
thresholds as decision-required").

**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.


## Sequential Scenario Planner UI semantic-defect reconciliation (Work Package 0, part 2)

**Context:** Section 6 of `Media-Mix-Lab: Coding LLM Next Steps After PR
#267 and Latest PRD Validation Updates` (2026-08-17) identified four
current semantic/architecture defects in the page-level sequential adapter
(`pages/08_Scenario_Planner.py`) that had to be corrected before treating
the manual sequential-planning UI path as governed: (1) the shared plan
start month is silently ignored and the analyst's entered monthly values
are re-seated onto a different real calendar - changing seasonality/cost
context without disclosure; (2) partial-first-month pro-ration, phasing,
and per-week cost-mapping conversion were implemented only inside the
page, violating the thin-interface principle (`AGENTS.md`: "The interface
must call shared, tested application or analytical services"); (3) the
page automatically switches to exploratory mode and automatically applies
`hold_last_observed` to every eligible fitted exogenous control with no
explicit analyst choice; (4) the page supplies an all-zero future
promotion map with no visible UI element or label.

**Decision:** Resolved (1) without inventing a bridge-period/start-date
business contract - the brief explicitly permits "constrain the UI to the
supported start semantics and make the input calendar unambiguous" as an
alternative to a full contract. The sequential tab now shows an explicit
entered-month -> real-calendar-month reassignment table whenever the two
differ, and blocks calculation until the analyst checks an explicit
acknowledgment box. (3) and (4) are resolved the same way: each becomes an
explicit, checkbox-gated acknowledgment before any result is calculated
(never an automatic default), per the user's explicit direction that all
three should be a "blocking choice before results show" rather than a
"visible default with override." No new future-control-input or
promotion-schedule editor was built - those remain separately tracked,
larger UI features; the fix here is that the sequential path cannot
proceed on an unacknowledged assumption, not that every alternative input
mechanism now exists.

(2) is resolved by moving the arithmetic into `core.planning.phasing`
as three new functions -
`reseat_ordinal_monthly_plan_to_start_week`,
`phase_monthly_series_from_partial_start_calendar_day_overlap_v1`, and
`phase_monetary_plan_from_partial_start_calendar_day_overlap_v1` - mirroring
the existing whole-month functions' structure and provenance contract
exactly, with their own unit tests
(`TestReseatOrdinalMonthlyPlanToStartWeek`, `TestPhaseFromPartialStart`,
`TestMonetaryPhaseFromPartialStart` in `test_phasing.py`). This supersedes
the WP1-phasing decision log entry's earlier choice to keep this logic
page-local "for this package" pending "a second caller" - the current
brief's explicit instruction to move it now is a task-specific
implementation brief, which outranks that earlier engineering-decision
rationale per the repository's own authority hierarchy.

**Rejected alternative:** Threading the three new explicit-choice booleans
into `_evaluate_sequential_manual_plan`'s own signature and business logic
(rejected - the evaluation mathematics for exploratory hold-last and
zero-promotion were already correct and already fingerprinted via
`build_future_context`'s existing `future_context_fingerprint`; the actual
defect was that the page called the evaluator before consent existed, not
that the evaluator computed the wrong thing. Gating the *call* in the
render function keeps the fix minimal and leaves the evaluator's tested
contract unchanged).

**Impact:** `ancestry_mmm/core/planning/phasing.py` (three new functions);
`ancestry_mmm/pages/08_Scenario_Planner.py` (`_prorated_sequential_monthly_
values`/`_first_month_fragment_schedule` removed; `_phase_channel`
simplified to call the new core functions; `_render_sequential_manual_tab`
gained three acknowledgment gates before any evaluation call);
`ancestry_mmm/tests/test_phasing.py` (8 new tests for the three new
functions); `ancestry_mmm/tests/test_scenario_planner_apptest.py` (one new
test asserting the gate blocks by default; the existing render test
updated to acknowledge the gates before asserting results appear). No
change to `core.sequential_simulation`, `core.sequential_evaluation_
context`, or `core.planning.future_context` - the underlying evaluation
mathematics and fingerprinting are unchanged. mypy: `core/planning`
remains zero-tolerance clean; full-core ratchet unchanged at 241/241.

**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.


## Leakage-safe historical validation foundation (Work Package 1)

**Context:** REQ-LEAK-001 (approved Work Package 0) required making
historical validation reconstruct the information state available at
each fold, rather than trusting a caller-supplied date slice. `core.
diagnostics.expanding_window_backtest` already existed but performed only
a bare date-sliced train/test split with no way to verify whether the
preprocessing state behind the supplied dataframe was itself leakage-safe.

**Decision:** Added `core/validation_folds.py`: `ValidationFold` (a typed,
versioned fold manifest - fold ID, train/test window, market/outcome
scope, and an `information_cutoff` that defaults to the fold's own
`train_end`, not "today" - the leakage-safe semantic is "what was
knowable exactly at the end of this fold's training window", never "what
do we know today with the benefit of every subsequent revision"),
`build_expanding_window_folds` (the same boundary arithmetic `expanding_
window_backtest` uses internally, extracted into inspectable objects),
`assess_fold_source_reconstruction` (per-variable leakage assessment
against a `core.coverage.VariableCoverageMatrix`, reusing `core.
frequency_alignment.check_publication_leakage`/`check_definition_break_
crossing` rather than inventing a second leakage-detection mechanism -
flags a variable not yet effective, crossing an unapproved definition
break, subject to publication-lag leakage as of the fold's cutoff, or
overlapping an `unavailable_source`/`unknown` coverage segment as
`cannot_verify`, the last of which is guaranteed to also record a
fold-level limitation so it can never be silently treated as safe), and
`leakage_safe_expanding_window_backtest` (builds folds, assesses each,
and - the key contract guarantee - never calls `fit_fold_fn` for a fold
the assessment did not clear).

`core.diagnostics.expanding_window_backtest` itself is completely
unchanged - this is an additive module, not a silent upgrade of that
helper's contract, per REQ-LEAK-001's own instruction not to present the
existing helper as satisfying the stronger contract. A dedicated test
(`test_does_not_mutate_expanding_window_backtest`) asserts the original
function's output has no `leakage_safe` column and remains fully usable.

**Scope boundary (recorded, not silently assumed complete):** this
assessment verifies what `VariableCoverageMatrix` metadata can prove
(effective periods, publication lag, definition breaks, coverage-segment
ambiguity). It does not rebuild the full model-ready `frame`/scaling/
mixed-frequency pipeline per fold from raw sources - REQ-LEAK-001
requirement 2's "scaling fit on training data only" and "lag/adstock/
state initialisation" items remain a contract for a future real-model-
integration pass. `DiagnosticsArtefact`/Diagnostics-page wiring is also
deferred, so it can be designed once, jointly with Work Package 2's
structural-stability evidence (REQ-LEAK-001 requirement 6 requires the
two share one fold-manifest notion, not two divergent ones).

**Rejected alternative:** Wiring this evidence into `DiagnosticsArtefact`
(a new schema v8 section) and the Diagnostics page in this same package
(rejected - Work Package 2's structural-stability evidence is explicitly
required to consume the same fold manifests; building the schema/UI
integration now and again for WP2 risks two divergent implementations of
"what a fold reconstructed". Building the typed core contract with fast,
synthetic, injected-fit-function tests first - exactly what the brief's
own WP1 instructions ask for - and deferring the shared UI/schema
integration to when both consumers exist is the narrower, lower-risk
sequencing).

**Impact:** `ancestry_mmm/core/validation_folds.py` (new);
`ancestry_mmm/tests/test_validation_folds.py` (new, 30 tests - fold
construction/validation, fold-boundary and no-future-leakage-in-split
blocking tests, per-variable leakage assessment across every status, and
the key blocking test proving a failed-assessment fold never reaches
`fit_fold_fn`); `docs/approved_requirements/REQ-LEAK-001.md` (Capability
status, Affected modules, Required tests, and Unresolved decisions
updated to reflect what is implemented and what remains);
`docs/approved_requirements/index.json` (updated); `docs/specification_
authority.md` (gap-table row updated). No change to `core.diagnostics`,
`core.coverage`, or `core.frequency_alignment` - this module only
composes their existing, already-tested primitives. mypy: new module
clean under `--ignore-missing-imports --follow-imports=silent`; full-core
ratchet unchanged at 241/241. No schema, migration, or persisted-artefact
changes.

**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.


## Posterior predictive metric distributions (Work Package 2, part 1)

**Context:** REQ-PPD-001 (approved Work Package 0) required distinguishing
three analytical objects that had been at risk of conflation: a metric
(MAE/RMSE/sMAPE/WAPE/bias) calculated once from the posterior-mean
prediction (`core.diagnostics.error_metrics_by_outcome`, already
implemented under REQ-VAL-001); the distribution of that same metric
calculated independently per posterior predictive draw; and the posterior
predictive interval for the outcome itself (`posterior_predictive_
coverage`, already implemented, a separate object). No module computed
the second of these three.

**Decision:** Added `core.diagnostics.posterior_predictive_metric_
distributions` (Model A) and `core.market_specific_diagnostics.
posterior_predictive_metric_distributions_market_specific` (Model C),
both reusing `trace.posterior["mu"].stack(sample=("chain","draw"))` -
the exact posterior-draw-stacking convention `posterior_predictive_
coverage` already established - to compute each metric independently per
draw via straightforward numpy vectorisation (no per-draw Python loop).
The point-metric column is not recomputed independently; it is the
existing `error_metrics_by_outcome`/`error_metrics_by_outcome_market_
specific` value passed straight through, so the two can never silently
diverge. The draw-level mechanics are shared between Model A and Model C
via a private `_posterior_predictive_metric_distributions_core` helper,
matching `core.market_specific_diagnostics`'s own documented precedent
that `mu`'s shape does not depend on market-specificity (the same reason
`posterior_predictive_coverage` itself is reused unchanged for both model
types).

A test (`test_distribution_mean_differs_from_point_for_nonlinear_metric_
under_noise`) asserts the two point/distribution values are NOT forced
into numerical agreement under a noisy posterior - proving the
implementation preserves the substantive distinction REQ-PPD-001 exists
to create, rather than accidentally computing the same number twice. A
companion zero-noise test proves the reverse: with no posterior spread,
the distribution correctly collapses onto the point value, which required
fixing the test fixture to set fabricated `mu` draws to `predict_mu`'s own
deterministic output plus noise (not an unrelated synthetic value) - the
`test_diagnostics_artefact.py` fixture this file's fixture was modelled on
deliberately decouples its fabricated `mu` from `predict_mu(params)`, which
is fine for exercising unrelated `DiagnosticsService` plumbing but would
have made a zero-noise-collapse assertion meaningless here.

**Rejected alternative:** Wiring this evidence into `DiagnosticsArtefact`
(a new schema v8 section) and `pages/06_Diagnostics.py` in this same
package (rejected - REQ-STAB-001's structural-stability evidence is the
other half of Work Package 2 and is expected to land in the same
Diagnostics-page view, since the brief requires the UI to separate
predictive quality, predictive stability, structural stability,
identification and approval readiness as one coherent update. Building
the schema/UI integration now and again for the structural-stability
follow-up risks two uncoordinated additions to the same page; landing the
typed core contract first, exactly as Work Package 1's REQ-LEAK-001
already did, keeps this PR narrow and defers the shared integration to
when both consumers exist).

**Impact:** `ancestry_mmm/core/diagnostics.py` (new: `posterior_
predictive_metric_distributions`, `_posterior_predictive_metric_
distributions_core`); `ancestry_mmm/core/market_specific_diagnostics.py`
(new: `posterior_predictive_metric_distributions_market_specific`);
`ancestry_mmm/tests/test_posterior_predictive_metric_distributions.py`
(new, 10 tests); `docs/approved_requirements/REQ-PPD-001.md`/`index.json`/
`docs/specification_authority.md` updated. Two new `trace.posterior[...]`
accesses on an `az.InferenceData`-annotated parameter are `# type:
ignore[attr-defined]` (the same pre-existing, already-tolerated mypy
limitation this exact access pattern already has everywhere else in
`core.diagnostics`/`core.market_specific_diagnostics`/`core.
identification_diagnostics` - explicitly suppressed here rather than
silently raising the full-core mypy ratchet past its 241 ceiling).
Full-core ratchet confirmed unchanged at 241/241 after the suppression.
No schema, migration, or persisted-artefact changes.

**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.


## Structural stability evidence across time-respecting folds (Work Package 2, part 2)

**Context:** REQ-STAB-001 (approved Work Package 0) required distinguishing
predictive stability (whether out-of-sample error is stable across folds -
already assessable via `core.diagnostics.expanding_window_backtest`/
`core.validation_folds`) from structural stability (whether decision-
driving quantities such as adstock decay, Hill K/S, media response
coefficients, baseline behaviour, hierarchy parameters, and selected
marginal economics move materially across the same folds) as two
genuinely separate evidence dimensions - a model can predict adequately
while its structural quantities drift, and neither `core.diagnostics` nor
`core.identification_diagnostics` compared anything across folds; both
compute their evidence on a single fit.

**Decision:** Added `core.structural_stability`: `FoldParameterSnapshot`
(one fold's decision-driving parameter point values and, where available,
posterior draws - the caller's own naming convention for parameter keys,
e.g. `"hill_K__TV"`), `ParameterFoldComparison` (the per-parameter
comparison across every fold that reported it, exposing only a plain
descriptive `point_range` - explicitly never a threshold, pass/fail
verdict, or materiality judgement, verified by a dedicated test asserting
no `status`/`verdict`/`pass`/`fail`/`stable`/`unstable` key exists in the
serialised output), and `StructuralStabilityArtefact`/`assess_structural_
stability` (the full structured comparison; a parameter missing from one
fold's snapshot is recorded as an explicit limitation, never silently
dropped or backfilled).

This module does not re-fit a model per fold - it accepts caller-supplied
snapshots, mirroring `core.validation_folds`'s own established Work
Package 1 pattern ("the caller supplies the fold-local computation, this
module only assembles and compares the result"). `FoldParameterSnapshot.
fold_id` is intended to match `core.validation_folds.ValidationFold.
fold_id`; an integration test proves fold IDs from `build_expanding_
window_folds` flow through this module's comparison unchanged, satisfying
REQ-STAB-001 requirement 6's "the two records share one notion of what a
historical fold is."

**Rejected alternative:** Wiring this evidence into `DiagnosticsArtefact`/
`pages/06_Diagnostics.py` now that both this record and `REQ-PPD-001`
have core contracts (rejected, on inspection - unlike `REQ-PPD-001`,
which only needs a single already-available trace/frame/meta/params call
and could genuinely be wired into `DiagnosticsService.evaluate()` today,
this record's evidence structurally requires *multiple folds' already
re-estimated* parameter values as input, and no real per-fold model
re-estimation pipeline exists anywhere in this repository yet - the same
expensive, unresolved "real-fold PyMC recovery" question `REQ-LEAK-001`
already recorded, not newly introduced here. Wiring an artefact section
that could only ever be populated by a caller manually assembling
synthetic snapshots would not be genuine evidence integration; it would
create the appearance of a working feature with no real data behind it.
The schema/UI work for both records remains a coherent follow-up once a
real multi-fold re-estimation path exists).

**Impact:** `ancestry_mmm/core/structural_stability.py` (new);
`ancestry_mmm/tests/test_structural_stability.py` (new, 18 tests);
`docs/approved_requirements/REQ-STAB-001.md`/`index.json`/`docs/
specification_authority.md` updated (including a corrected note on
`REQ-PPD-001`'s own gap-table row explaining precisely why its UI wiring
remains deferred). No change to `core.diagnostics`, `core.validation_
folds`, or any persisted artefact. mypy: new module clean; full-core
ratchet unchanged at 241/241.

**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.


## Estimand-specific graphical identification (Work Package 3)

**Context:** REQ-IDENT-001 (approved Work Package 0) required a diagnostic
distinct from `core.causal_graph.validate_causal_graph` (structural
validation - bad controls, cycles, roles) and `core.identification_
diagnostics` (fitted-model evidence - posterior correlation, condition
number): for a *specific requested estimand* (a treatment, an outcome,
and a proposed adjustment set), assess open backdoor paths, treatment
descendants incorrectly included as controls, colliders opened by
conditioning, and whether a minimal valid adjustment set exists - Pearl's
back-door criterion, applied to the approved causal graph.

**Decision:** Before writing any graph-theory code, checked Context7
against `/networkx/networkx` (root `AGENTS.md`'s required upstream-
reference workflow) rather than hand-deriving d-separation logic.
Confirmed NetworkX 3.5 introduced (and, per its own 3.5 release notes,
simultaneously retired the older `d_separated`/`minimum_d_separator`
names in favour of) `is_d_separator`, `is_minimal_d_separator`, and
`find_minimal_d_separator` (`networkx.algorithms.d_separation`) - the
exact primitives Pearl's back-door criterion needs. Added `networkx>=
3.5,<4.0` as a new dependency (pure-Python, MIT, `pip-audit`-clean
against the updated lock file) rather than reimplementing d-separation
from scratch, per root `AGENTS.md`'s "prefer supported public APIs...
do not reimplement upstream functionality without a documented reason."

`core.estimand_identification.assess_backdoor_identification`: builds a
plain `nx.DiGraph` from the approved `CausalGraph` (excluding
`excluded_diagnostic_only` edges, which "compile to nothing" per
REQ-GRAPH-001 and are not genuine causal relationships); removes the
treatment's outgoing edges to form the "backdoor graph" (the standard
Pearl transformation); checks `is_d_separator` on the proposed adjustment
set; separately checks, in the *original* (non-backdoor) graph, whether
any proposed member is a descendant of treatment (Pearl's second
condition, which a bare d-separation check on the backdoor graph alone
does not enforce); and, for each proposed member, checks whether removing
it alone would improve separation - a member whose removal helps is
flagged as a likely collider/collider-descendant. Verified against a
hand-constructed collider scenario (a path already blocked by a collider
by default, which conditioning on it wrongly reopens, alongside a genuine
confounder that does need adjustment) to prove the collider-flagging
logic actually distinguishes the two cases rather than merely happening
to pass a simpler test.

`EstimandIdentificationResult` never exposes a bare boolean "identified"
field - only the five-value status vocabulary Part 10 §17.7 suggested,
plus a mandatory `disclaimer` field carrying REQ-IDENT-001 requirement
1's exact wording, so a caller cannot access a result without also
receiving the "this is not proof" qualification. Every result also
records an explicit limitation that this checker cannot determine
whether a graph node corresponds to observed data (`core.causal_graph.
CausalNode` has no observability field) - never silently assumed either
way.

`effect_type="direct"` returns `unsupported_by_current_checker` rather
than silently applying the total-effect back-door criterion to a
direct-effect request - direct/natural-direct effect identification needs
a different criterion this module does not implement (REQ-IDENT-001
requirement 4's separation from structural/linked-model identification).

**Rejected alternative:** Hand-implementing backdoor-path enumeration and
d-separation from first principles (rejected - this is exactly the kind
of well-established graph algorithm root `AGENTS.md`'s upstream-reference
workflow exists to prevent reimplementing; `networkx` is a small,
mature, MIT-licensed, pure-Python dependency with no meaningful
supply-chain concern, and using its own vetted implementation is safer
than an Ancestry-specific reimplementation of a subtle algorithm where a
bug could silently misreport identification status).

**Impact:** `ancestry_mmm/core/estimand_identification.py` (new);
`ancestry_mmm/tests/test_estimand_identification.py` (new, 18 tests);
`pyproject.toml`/`uv.lock` (new dependency `networkx>=3.5,<4.0`);
`docs/approved_requirements/REQ-IDENT-001.md`/`index.json`/`docs/
specification_authority.md` updated. No change to `core.causal_graph`,
`core.graph_model_compiler`, or `core.identification_diagnostics`. mypy:
new module clean; full-core ratchet unchanged at 241/241. `pip-audit`
against the updated lock file: no known vulnerabilities. Deferred:
`core.graph_model_compiler` blocking-error extension (REQ-IDENT-001
requirement 5) and `DiagnosticsArtefact`/Diagnostics-page wiring
(requirement 6), both separate integration follow-ups.

**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.


## Latent-state scale and location identification (Work Package 3, second record)

**Context:** REQ-LATENT-001 (approved Work Package 0) required a
model-agnostic contract for declaring and empirically checking the
identifying strategy behind any fitted latent causal state (e.g.
Candidate A's `latent_branded_search_demand`). No module in the
repository previously declared or validated such a strategy - prior
regularisation alone was never a substitute for a genuine identifying
constraint (requirement 2).

**Decision:** Implement `core.latent_state_identification` as a
standalone, model-agnostic module: `LatentStateIdentificationDeclaration`
stores one of five approved strategy kinds plus a required, non-empty
description and optional anchor reference - the identifying choice is
recorded explicitly, never left implicit in code. `assess_latent_state_
identification` resolves a closed four-value status
(`identified`/`review_required`/`not_identified`/`unsupported_by_
current_checker`): no declaration is `not_identified` outright; a
declaration with no supplied posterior draws is `review_required`
(declared but not yet empirically checked under sampling); fewer than
two supplied chains is `unsupported_by_current_checker`; two or more
chains are compared by each chain's median of a caller-supplied
representative scalar, and disagreement in sign across chains - a
structural indeterminacy, not a graded threshold - is `not_identified`
with `sign_flip_detected=True`. `scale_drift_ratio` is always reported
as descriptive evidence only, mirroring `core.structural_stability.
ParameterFoldComparison.point_range`'s "report movement, never a
verdict" pattern from Work Package 2 part 2, since no scale-drift
materiality threshold has been approved. `is_eligible_for_official_use`
implements requirement 5's fail-closed use-eligibility gate: only
`identified` is eligible for official causal reporting, curve
publication, planning, or optimisation for the affected pathway - every
other status, including `review_required`, fails closed, mirroring the
existing Search fail-closed pattern for an unwired Candidate A pathway
(REQ-SEARCH-002). Every result carries a fixed disclaimer and never
exposes a bare boolean. This module does not fit or re-fit a model -
the caller supplies the declaration and, optionally, per-chain
posterior draws, mirroring `core.structural_stability`'s established
"the caller supplies the fold-local computation" pattern from Work
Package 2 part 2.

This module does **not** modify `core.search_capacity` and does not
assert or imply any specific identifying anchor for Candidate A's
latent branded-search demand. Candidate A's actual anchor (`MD-021`) is
an explicitly unresolved statistical modelling decision per
REQ-LATENT-001's own "Unresolved decisions" section and the PRD-
authority instruction governing this program: do not implement directly
from PRD prose without an approved requirement or decision package, and
do not guess an unresolved statistical, causal, business, or governance
decision. Requirement 3 (`core.graph_model_compiler` blocking-error
extension for unresolved latent-state identification) and the remaining
two sub-items of requirement 4 (full synthetic-recovery validation and
decision-instability detection, both of which require a real fit/re-fit
pipeline this module does not run) are deferred as separate integration
follow-ups, consistent with how REQ-IDENT-001 deferred its own
equivalent compiler-blocking requirement earlier in this same work
package.

**Rejected alternative:** Baking a specific identifying anchor for
Candidate A's `latent_branded_search_demand` directly into `core.
search_capacity` as part of this record (rejected - REQ-LATENT-001
explicitly reserves this as a decision-required statistical choice, not
resolvable by a reconciliation record or by this coding pass; guessing
an anchor would silently determine what one unit of the latent state
means, which requirement 2 requires to be a substantive, deliberate
choice).

**Impact:** `ancestry_mmm/core/latent_state_identification.py` (new);
`ancestry_mmm/tests/test_latent_state_identification.py` (new, 26
tests); `docs/approved_requirements/REQ-LATENT-001.md`/`index.json`/
`docs/specification_authority.md` updated. No change to `core.
search_capacity`, `core.graph_model_compiler`, `core.estimand_
identification`, or `core.structural_stability`. mypy: new module
clean; full-core ratchet unchanged at 241/241. No new dependency.
Deferred: `core.graph_model_compiler` blocking-error extension
(REQ-LATENT-001 requirement 3), full synthetic-recovery/decision-
instability validation (remainder of requirement 4), and
`DiagnosticsArtefact`/Causal-Graph-page wiring - all separate
integration follow-ups.

**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.


## Experiment evidence modes and provenance (Work Package 4, first record)

**Context:** REQ-EXPMODE-001 (approved Work Package 0) required a
governed evidence-mode contract for every experiment-to-model
relationship - Experiment Evidence existed only as an input data domain,
with no module declaring which of `validation_only`/`prior_calibration`/
`likelihood_calibration`/`diagnostic_comparison` applied to a given use,
no compatibility gate before a calibrating use, and no double-counting
check. Registering an experiment must never silently calibrate a model
(requirement 2's explicit text).

**Decision:** Implement `core.experiments` as a standalone registry and
evidence-mode module. `ExperimentRecord` is immutable and versioned,
following exactly the lineage/version pattern already established by
`core.causal_graph` (`graph_id`/`graph_version`) and `core.
search_objects` (`search_object_id`/`search_object_version`) -
`new_experiment_version`/`current_experiment_versions` mirror `core.
search_objects.new_search_object_version`/`current_search_object_
versions` exactly, rather than inventing a fourth divergent versioning
scheme. `ExperimentToModelUse` enforces requirement 2's closed
four-value evidence-mode vocabulary and requires the affected prior's
or likelihood term's name and version for a calibrating use, or
construction raises. `CompatibilityAssessment`/`assess_experiment_
compatibility` implement requirement 3's per-dimension compatibility
record across all nine required dimensions (outcome, estimand, market/
segment/product, channel/activity definition, treatment, counterfactual,
spend/delivery range, time horizon, effect scale) - this module has no
domain knowledge of what makes two markets or channel definitions
compatible, so every dimension is caller-supplied evidence, never
inferred by this module. `build_calibrating_use` is the only
constructor for a calibrating use and is fail-closed: it raises unless
`CompatibilityAssessment.is_fully_compatible` is `True`, directly
implementing "an incompatible experiment must not calibrate
automatically." `validate_no_double_counted_dependence` implements
requirement 2's double-counting rule: flags an experiment used via two
different calibrating modes against the same model unless every such
use records a `dependence_handling_method`. `ExperimentProvenanceReport`
/`build_provenance_report` implement requirement 6: every contributing
experiment's evidence mode, estimand, version, and uncertainty
individually - the module offers no function that collapses this list,
so a portfolio summary can only ever be additive, never a replacement.

Registering an `ExperimentRecord`/`ExperimentToModelUse` cannot silently
calibrate a model because nothing in this repository yet reads this
registry to build a model - `core.search_capacity`, `core.pathways`,
and every other model-fitting module are untouched by this record.

**Rejected alternative:** Choosing and implementing a specific
likelihood-calibration or prior-calibration statistical mechanism as
part of this record (rejected - REQ-EXPMODE-001's own "Explicitly
excluded" section explicitly reserves this for a future Work Package 4
decision-support package using Context7/official PyMC/PyMC-Marketing
sources before any production default is chosen, per the PRD-authority
instruction governing this program: do not guess an unresolved
statistical decision).

**Impact:** `ancestry_mmm/core/experiments.py` (new);
`ancestry_mmm/tests/test_experiments.py` (new, 30 tests);
`docs/approved_requirements/REQ-EXPMODE-001.md`/`index.json`/`docs/
specification_authority.md` updated. No change to `core.search_capacity`,
`core.pathways`, `core.causal_graph`, `core.search_objects`, or
`core.persistence`. mypy: new module clean; full-core ratchet unchanged
at 241/241. No new dependency. Deferred: any calibration statistical
mechanism, `core.persistence` export/import wiring, and `REQ-CALIB-001`'s
dependent comparison contract (separate record, Work Package 4 part 2).

**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.


## Calibrated-versus-uncalibrated model comparison (Work Package 4, second record)

**Context:** REQ-CALIB-001 (approved Work Package 0) required a
comparison contract that must exist before any future calibration
mechanism may become official - no calibration mechanism exists in this
repository, and no module compared a calibrated model against the
uncalibrated model it came from. The record's own "Unresolved decisions"
explicitly left open "whether calibrated-model identity extends
`core.model_identity` or introduces a parallel calibration-identity
object."

**Decision:** Implement `core.calibration_comparison` reusing `core.
model_identity.ModelIdentity` directly rather than introducing a second,
parallel identity type - resolving that open question. `Calibrated
VsUncalibratedComparisonArtefact` and `CalibrationEventRecord` both
reject construction via `ModelIdentity.matches` unless the calibrated
and uncalibrated identities are genuinely distinct, directly enforcing
requirement 1 ("never an in-place mutation of the model it was
calibrated from"). `CalibrationComparisonMetric` represents requirement
2's comparison dimensions (posterior predictive performance, historical
holdout, media/structural parameters, adstock/saturation, baseline,
hierarchy, posterior uncertainty, response curves, marginal economics,
planning/optimisation consequences) generically by caller-supplied name
and value - this module has no domain knowledge of how to compute any
specific one of them, mirroring `core.structural_stability`'s "the
caller supplies the computation" pattern from Work Package 2 part 2.
`difference` is descriptive only. `ExperimentAgreementComparison`
reports each compatible experiment's agreement individually, mirroring
`core.experiments`'s own "never collapsed into an average" pattern from
this same work package's first record. Requirement 3 ("closer agreement
with an experiment is not automatically preferred") is enforced by
omission - no threshold, pass/fail, or "calibration preferred" field
exists anywhere in the module - and verified by an explicit test that
scans every dataclass field on the comparison artefact for a forbidden
verdict-shaped name, the same discipline `core.structural_stability`
already established with its own `test_no_threshold_or_verdict_field_
exists`. `CalibrationEventRecord` implements requirement 5: resolved-
prior-conflict, materially-changed-decision, a closed three-value
uncertainty-change vocabulary, and improved/worsened validation
dimensions and new limitations are all caller-supplied structured facts
for a human reviewer to record, never a judgement this module computes.

**Rejected alternative:** Introducing a parallel `CalibrationIdentity`
type distinct from `core.model_identity.ModelIdentity` (rejected - a
calibrated model is still a model with a model_run_id/data/spec/
posterior fingerprint; inventing a second identity concept for the same
underlying thing would fragment identity handling across the codebase
for no benefit, and `ModelIdentity.matches` already gives exactly the
distinctness check requirement 1 needs).

**Impact:** `ancestry_mmm/core/calibration_comparison.py` (new);
`ancestry_mmm/tests/test_calibration_comparison.py` (new, 14 tests);
`docs/approved_requirements/REQ-CALIB-001.md`/`index.json`/`docs/
specification_authority.md` updated. No change to `core.model_identity`,
`core.experiments`, or `pages/06_Diagnostics.py`. mypy: new module
clean; full-core ratchet unchanged at 241/241. No new dependency.
Deferred: material-change criteria/thresholds, computing any specific
comparison metric, and Diagnostics-page UI wiring (requirement 4). No
calibration statistical mechanism exists or is implied -
`REQ-EXPMODE-001`'s own deferred decision-support-package question
remains open. This completes Work Package 4 as scoped by the
reconciliation brief.

**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.


## Sequential Scenario Planner terminal carryover and posterior uncertainty (Work Package 5 part 3)

**Context:** WP5 part 2 wired the sequential-weekly manual-plan tab
(`pages/08_Scenario_Planner.py`) into `ScenarioService.evaluate_manual_
sequential`, rendering weekly/monthly incremental tables and short/long
response-horizon metrics - but explicitly disclosed that terminal
incremental carryover and posterior uncertainty, though already fully
supported by the kernel and application layers (`core.planning.
terminal_response.evaluate_terminal_incremental_response[_market_
specific]`, `core.sequential_scenario_evaluation.evaluate_manual_
scenario_sequential`'s `terminal_future_context`/`trace`/`n_posterior_
draws` parameters, `SequentialManualScenarioInput.terminal_future_
context`/`.trace`/`.n_posterior_draws`), were not yet rendered in this
UI. Investigation confirmed the entire core/application/service chain
was already implemented and unit-tested (`test_terminal_response.py`,
`test_sequential_scenario_evaluation.py`'s `test_terminal_is_reported_
separately_when_requested`/`test_draw_consistent_posterior_path_
returns_full_per_draw_array`) - this was purely a UI-wiring gap, not a
missing kernel capability.

**Decision:** Wire both into `_evaluate_sequential_manual_plan`/
`_render_sequential_manual_tab`. Terminal: build a `terminal_future_
context` via `build_future_context` for `HorizonConfiguration().
terminal_continuation_weeks` (52) weeks immediately following the plan
window, continuing `historical_n_weeks + len(weeks)` (the same Fourier-
phase-continuation convention `core.planning.future_context` already
uses), reusing the exact same `future_mode`/hold-last-observed-controls/
zero-promo assumption set the analyst already acknowledged for the plan
window's own `future_context` - no new consent gate, since no new
assumption is introduced. Render `result.terminal.incremental` under a
"Terminal carryover (informational)" heading, structurally separate from
the weekly/monthly/horizon tables above (per `core.planning.terminal_
response`'s own "never folded into a plan-window result" contract).
Posterior: mirror the steady-state tab's own opt-in UX pattern exactly
(a checkbox - "re-runs the scenario once per sampled draw - slower" -
plus a 20-200 draw-count slider, both gated behind `trace is not None`)
rather than inventing a different UX for the same kind of expensive,
opt-in computation; pass the chosen draw count as `n_posterior_draws`
and always pass `trace` (the kernel's own `if trace is not None and
n_posterior_draws > 0` guard makes an unrequested `trace` a no-op).
Render a plan-window-total mean/median/90% credible-interval summary
computed by summing `result.posterior_weekly_incremental` per draw
across weeks *before* taking percentiles across draws - preserving
draw-to-draw correlation throughout (`REQ-SCEN-003`'s own "Posterior
aggregation" section: "aggregate draws only after the complete path...
has been evaluated per draw").

**Rejected alternative:** Re-deriving a new terminal/posterior
computation path independent of the already-implemented kernel
functions (rejected - the kernel/service layer already fully
implements and tests both; the only genuine gap was the UI call site
never populating `terminal_future_context`/`trace`/`n_posterior_
draws`, confirmed by an Explore-agent investigation before writing any
code, avoiding a redundant reimplementation).

**Impact:** `ancestry_mmm/pages/08_Scenario_Planner.py` (`_evaluate_
sequential_manual_plan` gains `trace`/`n_posterior_draws` parameters and
now also builds/returns `terminal_future_context`; `_render_sequential_
manual_tab` gains the posterior opt-in checkbox/slider and renders the
terminal-carryover and posterior-uncertainty sections in place of the
prior "not yet available" captions); `ancestry_mmm/tests/test_scenario_
planner_apptest.py` (new test: `test_sequential_weekly_manual_tab_
renders_terminal_carryover_section`, 36 tests total in this file, all
passing). No change to `core.sequential_scenario_evaluation`, `core.
planning.terminal_response`, or `application/scenario_service.py` - all
three were already complete. `docs/approved_requirements/REQ-SCEN-
001.md`/`REQ-SCEN-002.md`/`REQ-SCEN-003.md`, `docs/specification_
authority.md`, and `REPO_REVIEW_AND_NEXT_STEPS.md` updated to reflect
the closed gap. Still not yet implemented: sequential-weekly
optimisation, scenario persistence/staleness for a saved sequential
scenario, and a browser-level (Playwright) journey test for the
Scenario Planner page - all separate, explicitly disclosed follow-ups
(WP5 parts 4/5).

**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.


## Sequential Scenario Planner save/export and staleness (Work Package 5 part 4)

**Context:** WP5 part 3 left one remaining disclosed gap for the
sequential-weekly manual tab: "Saving a sequential scenario is not yet
available - only steady-state monthly scenarios can be saved and
exported in this release." An Explore-agent investigation before writing
any code confirmed this genuinely required new design work (unlike WP5
part 3's terminal/posterior gap, which was pure UI wiring onto an
already-complete kernel): `SequentialSimulationResult`, `Terminal
IncrementalResult`, and `SequentialScenarioEvaluationResult` had no
`to_dict`/`from_dict`, and no dict shape or schema had been sketched for
a persisted sequential scenario - REQ-SCEN-001's own "Not yet covered"
section confirmed no save/load path existed and no format had been
decided.

**Decision:** Add `to_dict`/`from_dict` to all three types, mirroring
`core.sequential_simulation.SequentialCarryInState.to_dict`'s established
"every numpy array becomes a plain list, every nested typed object
delegates to its own to_dict" pattern - no new serialization convention
invented. `core.sequential_scenario_evaluation.sequential_scenario_to_
dict` builds the persisted-scenario dict, appended to the SAME
`scenarios` list a steady-state scenario is (`core.optimization.
scenario_to_dict`) - never a separate parallel list, following this
session's repeated "reuse over fork" pattern (mirrors `core.calibration_
comparison` reusing `ModelIdentity` rather than inventing a parallel
identity type, WP4 part 2). This choice is a genuine, defensible
engineering decision (not a guessed statistical/business/governance
one): `core.optimization.validate_scenario_dependencies` was already made
engine-aware in WP5 (recognising both planning-semantics constants as
current), so a unified list with a `calculation_method` discriminator is
the natural continuation of that existing direction, not an invented
alternative.

Because a sequential scenario dict has no `spend_plan`/`objective`/
`scenario_plan` in the steady-state shape `core.optimization.scenario_
from_dict`'s legacy-migration logic assumes, that function gained an
early guard: `if d.get("calculation_method") == "sequential_weekly":
return d` - a genuinely new schema starting now, with nothing to migrate
from, passes through unchanged rather than having steady-state-specific
fields spuriously injected into it. `core.persistence.export_project`/
`import_project` needed NO changes at all: the generic scenario-export
loop already treats any non-`predicted`-DataFrame dict as plain
`json.dumps`-able metadata, and `SequentialScenarioEvaluationResult.
to_dict()` guarantees the whole dict already is - confirmed by an
explicit `export_project`/`import_project` round-trip test in `test_
persistence.py`, not merely by code inspection (the corresponding claim
in the pre-implementation investigation was verified, not assumed).

Staleness reuses the SAME cost-mapping/counterfactual-policy check the
steady-state path already had (both dict shapes carry `governance_
dependencies` identically, since `sequential_scenario_to_dict` populates
it from `result.governance_dependencies.to_dict()` the same way `scenario_
to_dict` does) - factored into a shared `_filter_current_scenarios`
helper on the page rather than duplicated. `core.optimization.compare_
scenarios` still requires a `predicted` DataFrame no sequential scenario
dict carries, so the page splits saved scenarios by `calculation_method`
before comparing, rendering saved sequential scenarios in a separate
"Saved sequential-weekly scenarios" summary (plan-window-total weekly
incremental per outcome) instead of forcing them through the steady-
state-only comparison table.

**Rejected alternative:** A separate `sequential_scenarios` persisted
list, parallel to `scenarios` (rejected - would require a second
export/import code path, a second staleness check, and a second "Saved
scenarios" UI section for no benefit; the unified-list-with-
discriminator design already required by `validate_scenario_
dependencies`'s existing engine-awareness extends cleanly to persistence
too, and `core.persistence`'s generic JSON-metadata handling already
supports an arbitrary dict shape without any DataFrame-specific
assumption baked in beyond the single `predicted` key check).

**Bug caught during review:** an earlier edit to the AppTest file
accidentally spliced a new test's body into the middle of the previous
test function (a stray trailing assertion from WP5 part 3's own test
ended up appended after the new test's final assertion, with no `def`
boundary between them, silently becoming part of the new test's body).
Caught by an unexpected test failure during verification, not by
inspection - fixed by restoring the correct function boundaries. A
reminder that a large multi-part edit into an existing test file needs
its result read back, not just its diff trusted.

**Impact:** `ancestry_mmm/core/sequential_simulation.py`
(`SequentialSimulationResult.to_dict`/`.from_dict`); `ancestry_mmm/core/
planning/terminal_response.py` (`TerminalIncrementalResult.to_dict`/
`.from_dict`); `ancestry_mmm/core/sequential_scenario_evaluation.py`
(`SequentialScenarioEvaluationResult.to_dict`/`.from_dict`,
`sequential_scenario_to_dict`); `ancestry_mmm/core/optimization.py`
(`scenario_from_dict`'s sequential-scenario passthrough guard);
`ancestry_mmm/pages/08_Scenario_Planner.py` ("Save this scenario" control
for the sequential tab; `_filter_current_scenarios` helper; a separate
"Saved sequential-weekly scenarios" summary section). Tests: `test_
sequential_scenario_evaluation.py` (+19: serialization round-trips with
and without terminal/posterior, `sequential_scenario_to_dict` JSON-
serializability/passthrough/staleness-field tests), `test_persistence.py`
(+1: full export/import round-trip), `test_scenario_planner_apptest.py`
(+1: save-button flow, 38 tests total in this file). mypy: ratchet
unchanged at 241/241. No new dependency. Deferred: sequential-weekly
optimisation and a browser-level (Playwright) journey test for the
Scenario Planner page - both separate, explicitly disclosed follow-ups.

**Owner:** Data Science / Platform engineering.
**Status:** Accepted; implemented on this work package's branch. PR and CI
remain the release gate.


## Sequential-weekly optimisation: reconciliation and decision package (Work Package 6)

**Context:** With Work Package 5 complete (sequential-weekly manual
evaluation fully wired: terminal carryover, posterior uncertainty, save/
export), the brief's own sequence names Work Package 6 as "sequential
monthly optimisation." Before writing any code, an Explore-agent
investigation (per this program's standing PRD-authority instruction:
no implementation without an approved requirement, and no guessing an
unresolved statistical/business/governance decision) confirmed two
blocking facts: no approved requirement record exists for sequential-
weekly *optimisation* (only manual evaluation is covered by `REQ-SCEN-
001`/`002`/`003`), and wiring the sequential kernel into `core.
optimization`'s existing search loop is not a mechanical rewiring.

**Finding - tractability:** `core.optimization.optimize_scenario`'s
search (`scipy.optimize.minimize`, method `SLSQP`, no analytic Jacobian
supplied) finite-differences its objective, calling the existing
analytic, per-month, state-independent steady-state response function
roughly `(n_months x n_channels + 1)` times per iteration - potentially
hundreds to low thousands of calls per optimisation run.
`core.sequential_scenario_evaluation.evaluate_manual_scenario_
sequential` performs a full week-by-week state-transition (adstock
carry-in) simulation per call, with no possible partial re-evaluation
(each week depends on the previous week's state), and optionally loops
that entire simulation once per requested posterior draw. Calling it
directly inside SLSQP's finite-difference inner loop replaces today's
cheap analytic objective with a materially more expensive computational
problem per candidate plan - untested at realistic plan sizes, and
plausibly intractable at interactive UI latency.

**Finding - objective definition:** the sequential contract natively
produces at least three distinct incremental-outcome quantities per
candidate plan (short-horizon, long-horizon, and terminal carryover -
the last already forbidden from the optimisation objective by
`REQ-SCEN-003` without a separately approved requirement). Steady-state
optimisation has one unambiguous per-month value to sum; sequential
optimisation does not, until one of these (or an approved combination)
is chosen as the target. This is a business/statistical decision, not
an engineering one.

**Decision:** Reconcile the gap into `REQ-SCEN-004` (target-state
contract only, explicitly not approved for implementation) and write
`docs/wp6_sequential_optimisation_decision_package.md`, laying out four
tractability candidates (T1 direct replay; T2 reduced-evaluation-budget
search; T3 two-stage steady-state-search-then-sequential-report; T4 a
validated fast surrogate used only inside the search loop) and four
objective candidates (O1 plan-window total; O2 short-horizon only; O3
long-horizon only; O4 an approved weighted combination), with tradeoffs
for each - none selected by this coding pass, per the same "candidate
formulations, not a chosen answer" pattern already established by
`docs/search_mediation_capacity_decision_wp3.md` (Work Package 3 of the
prior brief). Stopping this workstream here, rather than guessing a
tractability strategy or an objective weighting, is the explicit
instruction this program operates under.

**Rejected alternative:** Implementing Candidate T1 (direct replay)
with Candidate O1 (plan-window total) unilaterally, on the reasoning
that they are the "simplest" or "most obvious" choices (rejected - T1's
actual runtime at realistic plan sizes was never measured, so shipping
it could silently produce an unusably slow or numerically unstable
optimiser in production; O1 is a defensible default but is still a
business framing choice about what "the plan's value" means under
sequential semantics that deserves an explicit decision, not an
assumed one, especially given `REQ-SCEN-003` already treats the
analogous terminal-carryover-in-objective question as approval-gated
rather than default-permitted).

**Impact:** `docs/approved_requirements/REQ-SCEN-004.md` (new),
`docs/wp6_sequential_optimisation_decision_package.md` (new),
`docs/approved_requirements/index.json` (updated), `docs/
specification_authority.md` (gap-table row updated),
`REPO_REVIEW_AND_NEXT_STEPS.md` (updated). No code changes - `core.
optimization.py`, `core.sequential_scenario_evaluation.py`, and
`pages/08_Scenario_Planner.py`'s optimiser tabs are all untouched by
this package. This workstream (sequential-weekly optimisation) is
stopped pending review of the decision package; the program continues
autonomously to the next work package in the brief's sequence
(Work Package 7).

**Owner:** Data Science / Platform engineering (decision required before
any implementation).
**Status:** Decision-support package delivered; awaiting human review and
selection. No implementation PR accompanies this entry.


## Candidate A final-outcome replay decision package (Work Package 7)

**Context:** `REQ-SEARCH-002` approved Candidate A (structural latent
demand with hard censoring) as the production Search mediation/capacity
formulation on 2026-08-15 - that choice is settled. Since that record's
own Work Package 3, `core.predict.predict_mu` and (later)
`core.sequential_simulation.simulate_sequential_outcomes` have both
raised `CandidateAReplayNotSupportedError` for a Candidate A fit,
explicitly deferring "full replay integration" as "a genuine modelling
design question, not a mechanical extension." An Explore-agent
investigation before writing anything confirmed this question had never
been given its own decision-support document - only the formulation-
choice package (`docs/search_mediation_capacity_decision_wp3.md`, a
different question, already resolved) and Work Package 6's optimisation-
tractability package (a different question again) exist.

**Finding:** Candidate A's demand/capture/cap chain
(`core.search_capacity.add_search_candidate_a_to_model`) computes
`latent_branded_search_demand`, `capture_shares` (Dirichlet-allocated),
`realised_paid_search_delivery` (`min(paid_opportunity, cap)`),
`organic_capture`, `direct_navigation_capture`, and finally `search_eta_
contribution` as **fit-time deterministics** over the historical,
adstocked/saturated upstream media and a fixed, *observed* `cap` array
(`fit_inputs.paid_search_cap` - not a latent parameter, not forecastable
by the fitted model itself). Nothing in the current model defines this
chain as a function `predict_mu`/`simulate_sequential_outcomes` can
re-evaluate at an arbitrary candidate spend level, unlike the ordinary
media/baseline/trend/season/promo/controls terms those functions already
replay. Four genuinely open sub-questions block "full replay
integration," not one: (1) how upstream media is supplied at a
hypothetical spend point; (2) how the paid-search cap - a fixed
historical input with no observed value in a future/planned period - is
specified counterfactually; (3) how far outside the historically
observed spend/cap range a replay may extrapolate; (4) how posterior
uncertainty propagates through the cap's `min(...)` non-linearity
(concave, so `E[min(X, cap)] <= min(E[X], cap)` by Jensen's inequality
whenever `X` is posterior-drawn near the cap-binding region - not a
hypothetical edge case for a Dirichlet-allocated capture share).

**Decision:** Write `docs/wp7_candidate_a_final_outcome_replay_
decision_package.md`, laying out two upstream-media candidates (direct
re-evaluation; range-restricted re-evaluation), three cap-specification
candidates (reuse `core.planning.future_context`'s existing hold-last-
observed/explicit-future-value pattern already approved for exogenous
controls; require an explicit new governed planning input; treat the
cap as unconstraining for planning purposes, changing what the replayed
number represents), three extrapolation-policy candidates (unbounded;
bounded-and-flagged, mirroring `core.curve_artifact`'s existing
extrapolation-status contract; hard-blocked outside an approved
tolerance), and two uncertainty candidates (point-estimate; draw-
consistent, mirroring `core.sequential_scenario_evaluation`'s existing
per-draw contract) - none selected. `REPO_REVIEW_AND_NEXT_STEPS.md`
item 4b updated to reference this package rather than only naming the
question as open.

**Rejected alternative:** Implementing Candidate M1 (direct re-
evaluation) with Candidate C1 (reuse future-context hold-last-observed)
and Candidate U1 (point-estimate only) unilaterally, on the reasoning
that they are the most direct application of already-approved patterns
elsewhere in the repository (rejected - "already approved elsewhere for
a different purpose" is not the same as "approved for this purpose";
the cap is a capacity ceiling, not an ordinary covariate, and silently
extrapolating a fitted demand curve to an arbitrary spend level while
ignoring the cap's non-linear effect on the outcome distribution is
exactly the kind of plausible-but-wrong number `CandidateAReplayNot
SupportedError` exists to prevent, per its own docstring).

**Impact:** `docs/wp7_candidate_a_final_outcome_replay_decision_
package.md` (new), `REPO_REVIEW_AND_NEXT_STEPS.md` (item 4b updated).
No code changes - `core.predict.py`, `core.sequential_simulation.py`,
`core.search_capacity.py`, `core.attribution.py`, and `core.curve_
artifact.py` are all untouched by this package; `CandidateAReplayNot
SupportedError` continues to be raised exactly as before. This
workstream is stopped pending review of the decision package; the
program continues autonomously to the next work package in the brief's
sequence (Work Package 8).

**Owner:** Data Science / Platform engineering (decision), Modelling
(counterfactual specification and extrapolation-policy review).
**Status:** Decision-support package delivered; awaiting human review and
selection. No implementation PR accompanies this entry.


## Ragged multi-market predictor decision package (Work Package 8)

**Context:** `REQ-COVERAGE-001` §6 already named `FR-MOD-015` (market-
specific/ragged predictor sets inside the hierarchical model equations)
as "explicitly not approved by this record" and listed three candidate
shapes without choosing among them, but no dedicated decision-support
document existed - only a fixed report string (`core.market_data_
capability.FR_MOD_015_DECISION_REPORT`) naming the shape of the decision
needed, referenced from several other work packages' own entries in this
log without ever being resolved by any of them. An Explore-agent
investigation confirmed this gap is structural, not merely an unapproved
runtime guard: `core.hierarchical_model.build_fh_hierarchical_model` and
`core.market_specific_model.build_fh_market_specific_model` both consume
a single `X_media` matrix where `market_bounds` slices only which *rows*
belong to which market, never which *columns* apply - every market must
supply every requested channel's genuine observed coverage, with no
runtime guard analogous to `CandidateAReplayNotSupportedError` because
the rectangular assumption is baked into the array shape the model-
building code consumes, one layer below where a guard could even be
inserted.

**Finding:** the genuine statistical ambiguity is prior to any
implementation choice: does "no coverage" mean a channel truly had zero
effect/spend in a market (a fact about the world), or that its exposure
there is unobserved but possibly non-zero (a fact about the data)? These
require different treatments, and `REQ-COVERAGE-001` S1's own "missing
is not zero" principle - enforced everywhere else in this repository's
data-coverage machinery - has no approved mechanical enforcement at this
one remaining boundary. The answer may not even be uniform across every
missing cell: `core.coverage`'s own governed missingness-state
vocabulary already distinguishes reasons a cell might lack coverage, and
whether the approved treatment should be a function of that recorded
reason (rather than one blanket rule) is an additional, cross-cutting
question this package raises.

**Decision:** Write `docs/wp8_ragged_multi_market_predictor_decision_
package.md`, elaborating `REQ-COVERAGE-001` §6's three named candidate
shapes with their tradeoffs - a masked/marginalised likelihood term
(statistically coherent under a pooled/hierarchical channel coefficient:
a market contributing no likelihood evidence for a parameter still
receives a posterior fully determined by the pooling prior, the standard
Bayesian treatment of "no information," but requires re-deriving how
`eta` is assembled per market); restructuring `X_media`/`market_bounds`
for genuinely ragged per-market columns (similar statistical intent, a
larger engineering shape touching the data-preparation layer too, and
raising its own unresolved sub-question of whether an unpooled
per-market coefficient should even exist for a channel a market never
had); and an explicit, governed zero-fill convention (cheapest, weakest
statistically, and - unlike the masked treatment - actively injects a
specific, possibly wrong signal that competes with the pooling prior
rather than contributing none) - plus the missingness-reason cross-
cutting question above. None selected. `REPO_REVIEW_AND_NEXT_STEPS.md`'s
`FR-MOD-015` bullet updated to reference this package.

**Rejected alternative:** Defaulting to Candidate R3 (zero-fill) on the
reasoning that it requires no engine changes and therefore "unblocks"
ragged markets fastest (rejected - `REQ-COVERAGE-001` S1's "missing is
not zero" principle exists precisely to prevent exactly this shortcut
elsewhere in the repository; applying it as a blanket default here would
be inconsistent with that already-approved principle and would silently
inject a specific, unverified signal into a hierarchical model's pooling
behaviour rather than the "no information" treatment a masked likelihood
term would give).

**Impact:** `docs/wp8_ragged_multi_market_predictor_decision_
package.md` (new), `REPO_REVIEW_AND_NEXT_STEPS.md` (`FR-MOD-015` bullet
updated). No code changes - `core.hierarchical_model.py`, `core.market_
specific_model.py`, `core.market_data_capability.py`, and `data.
preprocessor.py` are all untouched by this package; `check_engine_
capability` continues to report an unsupported request exactly as
before. This workstream is stopped pending review of the decision
package; the program continues autonomously to the next work package in
the brief's sequence (Work Package 9).

**Owner:** Data Science / Platform engineering (decision), Modelling
(missingness-reason taxonomy and hierarchy/pooling review).
**Status:** Decision-support package delivered; awaiting human review and
selection. No implementation PR accompanies this entry.


## Governed future-assumption bundle decision package (Work Package 9)

**Context:** `docs/specification_authority.md` already listed "Future-
assumption bundles" as "No approved requirement/decision yet", and
`REQ-FORECAST-001` (Work Package 0) named "Work Package 9's broader
'governed future assumptions' scope" without authorising it. An Explore-
agent investigation confirmed the gap is genuine and precisely bounded:
`core.planning.future_context` (`REQ-SCEN-002`) already implements a
careful, fail-closed per-control explicit/hold-last-observed contract for
one plan window, but has no bundle-level object collecting every future-
role assignment for a scenario with a single decision-readiness rollup,
no attachment point for `REQ-FORECAST-001`'s not-yet-implemented
consequence evidence, and no resolution of whether/how Chronos-2 or
another external forecaster (permitted but not selected by `AGENTS.md`'s
future-variable-role #2) may supply a bundle's future path.

**Finding:** three genuinely unresolved questions block any
implementation, each statistical/governance in nature rather than
mechanical: (1) the bundle's own schema/identity (a thin wrapper around
existing `FutureContextResult`s, an extension of that type itself, or a
separate fingerprint-keyed registry - `core.causal_graph`/`core.
experiments`'s existing immutable-and-versioned lineage pattern is the
closest precedent but does not by itself answer which shape fits here);
(2) materiality quantification/grading (`VL-027`/`RP-024`) - how much
forecast uncertainty or downstream consequence becomes decision-material,
and when review becomes blocking rather than advisory, inherited
unresolved from `REQ-FORECAST-001`; (3) external-forecaster integration -
`build_future_context`'s `explicit_future` parameter already accepts any
caller-supplied series today, forecast-derived or not, so no code change
is required merely to plumb a number through; the open question is
which method (if any) is trusted for official use and how that trust is
disclosed and audited.

**Decision:** Reconcile the gap into `docs/approved_requirements/
REQ-FUTURE-001.md` (target-state contract only, mirroring Work Package
6's `REQ-SCEN-004` pattern) and write `docs/wp9_future_assumption_bundle_
decision_package.md`, laying out three bundle-schema candidates (B1: thin
named wrapper around existing `FutureContextResult`s; B2: extend
`FutureContextResult` itself with bundle identity; B3: a separate
fingerprint-keyed registry, closer to `core.causal_graph`/`core.
experiments`'s identity/registry separation), three materiality-grading
candidates (M1: effect-size threshold on the consequence axis; M2:
decision-ranking-change detection with no absolute threshold; M3:
disclosed, ungraded consequence evidence only, consistent with `core.
calibration_comparison`'s established no-verdict-field precedent), and
three external-forecaster-integration candidates (F1: no production
integration, explicit-future-path only; F2: Chronos-2 behind an explicit
disclosed provenance flag; F3: a method-agnostic forecaster-interface
contract with Chronos-2 as one registered implementation, mirroring
`core.frequency_conversion`'s approved-method-catalogue pattern). None
selected. `docs/specification_authority.md`'s "Future-assumption
bundles" and "Downstream forecast-consequence evidence" rows, and
`REPO_REVIEW_AND_NEXT_STEPS.md`'s Chronos-2 bullet, updated to reference
this package.

**Rejected alternative:** Treating "no production Chronos-2 integration
yet" as sufficient reason to skip creating a requirement record at all
(rejected - the gap is broader than the forecaster-selection question
alone; the bundle-schema and materiality-grading questions exist even
under Candidate F1's "no external forecaster" branch, so a target-state
record and decision package are needed regardless of which forecaster
candidate is eventually chosen).

**Impact:** `docs/approved_requirements/REQ-FUTURE-001.md` (new),
`docs/approved_requirements/index.json` (new entry), `docs/wp9_future_
assumption_bundle_decision_package.md` (new), `docs/specification_
authority.md` (two rows updated), `REPO_REVIEW_AND_NEXT_STEPS.md`
(Chronos-2 bullet updated). No code changes - `core.planning.
future_context` is untouched by this package; it continues to serve one
plan window's per-control contract exactly as before. This workstream is
stopped pending review of the decision package; the program continues
autonomously to the next work package in the brief's sequence (Work
Package 10).

**Owner:** Data Science / Platform engineering (bundle schema, forecaster
integration), Modelling (materiality grading, forecast-consequence
review policy).
**Status:** Decision-support package delivered; awaiting human review and
selection. No implementation PR accompanies this entry.



## Time-varying latent baseline decision package (Work Package 10)

**Context:** `docs/specification_authority.md` already listed "Time-
varying baseline" as "No approved requirement/decision yet", pointing to
`AGENTS.md`'s future-variable-role #5 ("latent baseline state - the
time-varying intercept, projected from its own fitted statistical
process, never treated as an ordinary external control") as the standing
invariant. An Explore-agent investigation confirmed no `REQ-BASELINE-*`
record exists and no time-varying-intercept code path exists anywhere in
`core.hierarchical_model`/`core.market_specific_model` - both define
`intercept` as a single static `pm.Normal` per market/outcome (lines
805-812 and 441-448 respectively), never a function of time.

**Finding:** following this repository's "Required upstream-reference
workflow," the closest relevant `pymc-labs/pymc-marketing` implementation
was inspected (`MMM`'s `time_varying_intercept=True`, a Hilbert Space
Gaussian Process modelling the intercept's percentage deviation from a
fitted baseline) - and its own documentation states this component
"reverts to its prior mean and exhibits rapidly growing
uncertainty beyond the training data window," recommending trend/Fourier
continuation instead for forecasting or scenario planning beyond a short
horizon. This directly conflicts with `AGENTS.md` role #5's "projected...
for planning" language for the most obvious upstream implementation
choice, and raises a genuine, unresolved question this repository's
existing `core.hierarchical_model` trend/Fourier terms (already
deterministically continued forward by `core.planning.future_context`)
may already substantially address - whether a distinct time-varying-
baseline capability is even warranted for planning use, versus being
scoped to in-sample measurement/diagnostics only (e.g. explaining a past
competitor-launch or pandemic-style demand shift, pymc-marketing's own
stated use case). Separately, `REQ-LATENT-001`'s Requirement 1 already
anticipates "any future latent baseline state" needing an identifying
strategy, but a baseline has no obvious analogue to Candidate A's
capture-share Dirichlet anchor - which strategy would apply is not
decided by any existing record.

**Decision:** Reconcile the gap into `docs/approved_requirements/
REQ-BASELINE-001.md` (target-state contract only, mirroring Work Package
6's `REQ-SCEN-004` and Work Package 9's `REQ-FUTURE-001` pattern) and
write `docs/wp10_time_varying_baseline_decision_package.md`, laying out
three baseline-process candidates (T1: direct upstream HSGP adoption; T2:
a discrete-time random-walk-style process with different, potentially
more planning-suitable extrapolation behaviour but no upstream `pymc-
marketing` reference; T3: no new process, concluding existing trend/
Fourier continuation already satisfies role #5's planning intent) and
three forward-projection candidates (P1: measurement/diagnostics only, no
planning use; P2: hold at the fitted process's own implied steady-state/
prior-mean value, mirroring but not identical to `hold_last_observed`;
P3: restrict to a process with validated extrapolation behaviour before
any planning use). None selected. `docs/specification_authority.md`'s
"Time-varying baseline" row and `REPO_REVIEW_AND_NEXT_STEPS.md` updated
to reference this package.

**Rejected alternative:** Adopting Candidate T1 (direct upstream HSGP
adoption) by default on the reasoning that it is the named, documented
`pymc-marketing` pattern for this exact repository-invariant role
(rejected - upstream's own documentation explicitly cautions against
using that same component for forecasting/scenario planning beyond a
short horizon, which is precisely the planning use `AGENTS.md` role #5
requires; adopting it without also resolving the forward-projection
question (Candidate P) would silently ship a capability upstream itself
says is unsuited to the purpose it is meant to serve).

**Impact:** `docs/approved_requirements/REQ-BASELINE-001.md` (new),
`docs/approved_requirements/index.json` (new entry), `docs/wp10_time_
varying_baseline_decision_package.md` (new), `docs/specification_
authority.md` (row updated), `REPO_REVIEW_AND_NEXT_STEPS.md` (bullet
added). No code changes - `core.hierarchical_model`, `core.market_
specific_model`, `core.latent_state_identification`, and `core.planning.
future_context` are all untouched by this package; the intercept remains
a single static per-market/outcome scalar exactly as before. This
workstream is stopped pending review of the decision package; the
program continues autonomously to the next work package in the brief's
sequence (Work Package 11).

**Owner:** Modelling (baseline-process selection, identification
strategy, extrapolation validation), Data Science / Platform engineering
(implementation once a strategy is approved).
**Status:** Decision-support package delivered; awaiting human review and
selection. No implementation PR accompanies this entry.



## Capacity and cap semantics decision package (Work Package 11)

**Context:** `docs/specification_authority.md` already listed "Capacity
and cap semantics" as "No approved requirement/decision yet", pointing to
`AGENTS.md`'s "Capacity and cap invariants" section as the standing
business/mathematical invariant. `REQ-GRAPH-001`'s own governed-edge-role
table independently confirms the boundary: `capacity_constrained` is
"Supported only by the explicit Candidate A Search linked engine for its
authorised Search structure; unsupported for every other structure." An
Explore-agent investigation ranked this the strongest remaining gap in
`docs/specification_authority.md`'s "No approved requirement/decision
yet" rows after Work Packages 6/8/9/10 (ruling out a "Candidate A Model
C" hypothesis for Work Package 11 as a red herring with zero repo
evidence - that phrase conflates two unrelated naming schemes, curve-
fitting Model A/B/C variants and Search Candidate A/B/C formulations,
neither of which names an open gap).

**Finding:** inspecting Candidate A's existing implementation
(`core.search_capacity.candidate_a_forward`) against `AGENTS.md`'s
invariants surfaced concrete, specific gaps, not merely an absent record.
`cap_binding` is computed as `np.isclose(paid, cap, rtol=1e-8,
atol=1e-8)` - a strict two-value boolean - while `AGENTS.md` requires
four states (capped/uncapped/ambiguous/unavailable); neither "ambiguous"
(a posterior-uncertainty-driven near-boundary status - Candidate A's own
`CapBindingSummary.probability_cap_binding` already computes a per-draw
binding-probability distribution that could inform this, but nothing
currently derives a status from it) nor "unavailable" (no governed cap
value at all, distinct from a supplied cap of zero) is represented
anywhere. Separately, `EDGE_ROLE_CAPACITY_CONSTRAINED` is already generic
graph vocabulary, but the only compiler logic for it
(`core.graph_model_compiler`'s Candidate-A structural validator) is
pathway-specific, not a reusable contract - generalising from exactly one
existing example risks encoding accidental Candidate-A-specific
assumptions, a real design risk this package does not resolve.

**Decision:** Reconcile the gap into `docs/approved_requirements/
REQ-CAP-001.md` (target-state contract only, mirroring Work Packages 6/9/
10's `REQ-SCEN-004`/`REQ-FUTURE-001`/`REQ-BASELINE-001` pattern) and write
`docs/wp11_capacity_cap_semantics_decision_package.md`, laying out three
cap-hit-status candidates (S1: extend the existing boolean to a
threshold-based four-value enum; S2: report the full per-draw binding-
probability distribution with no single mandatory point label, mirroring
`core.calibration_comparison`'s established no-verdict-field precedent;
S3: leave status definitions per-pathway with no shared vocabulary) and
three generalisation-timing candidates (G1: extract a shared pathway-
agnostic module now; G2: defer generalisation until a second concrete
pathway exists, avoiding premature abstraction from one example; G3:
approve the vocabulary/invariants now while deferring the shared-module
question). None selected. `docs/specification_authority.md`'s "Capacity
and cap semantics" row and `REPO_REVIEW_AND_NEXT_STEPS.md` updated to
reference this package.

**Rejected alternative:** Extending `cap_binding` to a four-value enum
immediately inside `core.search_capacity` on the reasoning that it is a
narrow, mechanical addition to one existing module (rejected - the
"ambiguous" threshold is a genuine statistical judgement call with no
obvious default, and making the change inside Candidate A's own module
without first deciding the generalisation-timing question (G1/G2/G3)
risks baking a pathway-specific implementation into what `AGENTS.md`
frames as a cross-pathway invariant, exactly the premature-generalisation
or premature-narrowing risk this package exists to avoid guessing past).

**Impact:** `docs/approved_requirements/REQ-CAP-001.md` (new),
`docs/approved_requirements/index.json` (new entry), `docs/wp11_capacity_
cap_semantics_decision_package.md` (new), `docs/specification_
authority.md` (row updated), `REPO_REVIEW_AND_NEXT_STEPS.md` (bullet
added). No code changes - `core.search_capacity` and `core.graph_model_
compiler` are both untouched by this package; `cap_binding` remains a
strict boolean and `capacity_constrained` edges remain compilable only
for Candidate A's authorised Search structure exactly as before. This
workstream is stopped pending review of the decision package. Work
Package 11 is the last work package named in the reconciled brief's
sequence (Work Package 0 through Work Package 11) - the autonomous
coding program's implementation phase concludes here, with six
decision packages (Work Packages 6, 7, 8, 9, 10, 11) awaiting human
review and selection before any of their blocked implementation work
can proceed.

**Owner:** Modelling (cap-hit status semantics, reconciliation-identity
generality), Data Science / Platform engineering (module-sharing
architecture, cap-object governance mechanics).
**Status:** Decision-support package delivered; awaiting human review and
selection. No implementation PR accompanies this entry.

## Repository truth and local PRD safety (Post-PR284 Work Package 0)

**Context:** `Media-Mix-Lab: Coding LLM Next Steps After PR #284` identified
two live repository-truth defects: `README.md`'s Scenario Planner
description still claimed the sequential (weekly, state-transition) manual
evaluation method was "not yet wired into this page", false since PRs
#266/#267/#269/#277/#278 wired `sequential_weekly` into the "Edited plan
and calculated result" tab with historical carry-in, short/long response,
terminal carryover, posterior uncertainty, and save/export; and
`REPO_REVIEW_AND_NEXT_STEPS.md`'s "Repository state through merged PR
#269" leading marker was itself stale (PRs #270-#284 had merged on top of
it), which is the same drift failure the marker was originally introduced
to fix, one level up. The brief also flagged that the local PRD suite
under `docs/PRD/` (intentionally local-only, not pushed) had no local
Git-exclusion protection, making it vulnerable to a future broad `git add`.

**Decision:** (1) Corrected `README.md`'s Scenario Planner bullet and
"What's explicitly not built yet" section to state both manual evaluation
methods explicitly (steady-state monthly, used by the optimiser tabs;
sequential weekly, used by the manual tab, with historical carry-in,
short/long response, terminal carryover, posterior uncertainty, and
save/export/staleness), and that sequential-weekly *optimisation* (not
manual evaluation) remains the not-yet-implemented gap. (2) Replaced
`REPO_REVIEW_AND_NEXT_STEPS.md`'s "Repository state through merged PR
#<N>" leading milestone marker with fully static wording: this file
states capabilities and labelled history; live remote state is always
resolved from GitHub, never from this file. Historical entries may still
cite the specific PR they were merged in - that is a fact about the past,
not a claim about the present. (3) Replaced
`test_repo_review_does_not_use_a_necessarily_drifting_current_main_field`
with `test_repo_review_does_not_assert_a_global_current_pr_or_milestone_
marker`, which rejects both the live-SHA field and the "Repository state
through merged PR #<N>" marker as instances of the same anti-pattern,
rather than requiring the latter. (4) Added `/docs/PRD/` to `.git/info/
exclude` (verified with `git check-ignore -v`) - a local-only exclusion,
not a tracked `.gitignore` change; no PRD source file was staged, modified,
renamed, or committed.

**Rejected alternative:** Replacing "#269" with "#284" in the milestone
marker (rejected - the brief explicitly identified this as treating the
symptom; the marker would go stale again at the next merge exactly as it
already had once).

**Impact:** `README.md` (Scenario Planner bullet and "not built yet"
section corrected), `REPO_REVIEW_AND_NEXT_STEPS.md` (baseline section
rewritten to static wording), `ancestry_mmm/tests/
test_repository_status_conformance.py` (anti-drift test replaced), `.git/
info/exclude` (local-only, unpushed). No production code changes. Local
PRD suite under `docs/PRD/` confirmed untracked, unstaged, and now
locally excluded throughout this work package.

**Owner:** Platform engineering (documentation/tooling truth).
**Status:** Implemented.

## Real per-fold PyMC refit orchestration (Work Package 1 part 1)

**Context:** `REQ-LEAK-001` (leakage-safe fold contract) and `REQ-STAB-001`
(structural-stability comparison) were both built on a deliberate "the
caller supplies the fold-local computation" contract - and both explicitly
recorded, in their own "Unresolved decisions", that no real per-fold PyMC
re-estimation pipeline existed anywhere in the repository yet:
`core.validation_folds.leakage_safe_expanding_window_backtest`'s
`fit_fold_fn` had only ever been called with a fake (`test_validation_
folds.py`); `core.structural_stability.assess_structural_stability` had
only ever compared manually-constructed `FoldParameterSnapshot`s. The one
real per-fold refit in the repository was `pages/06_Diagnostics.py`'s
"Out-of-sample accuracy" backtest closure, wired to the plain,
non-leakage-safe `core.diagnostics.expanding_window_backtest`, producing
only R²/MAPE - no structural-stability evidence, and no leakage-safety
proof.

**Decision:** Added `ancestry_mmm/application/fold_refit_service.py`:
`fit_fold_with_real_model` runs the real production fit sequence
(`data.prepare_fh_modeling_frame` -> `application.model_fit_service.
build_model_for_spec` -> `core.models.fit_model` -> `core.predict.
extract_posterior_params`/`core.market_specific_predict.
extract_market_specific_posterior_params`) - reused, never a second
validation-only model engine - and extracts a genuine `FoldParameterSnapshot`
from the fitted trace (point values from the posterior mean; draws from a
subsample of real `(chain, draw)` pairs via the same `core.uncertainty.
sample_draw_indices` approximation `core.uncertainty` already uses
elsewhere). `run_leakage_safe_fold_refit` reimplements `leakage_safe_
expanding_window_backtest`'s own fold-selection loop (`build_expanding_
window_folds` + `assess_fold_source_reconstruction`, both already public)
rather than widening that helper's tested `fit_fold_fn` contract or fitting
each fold twice - so a real fit happens exactly once per accepted fold,
producing both the R²/MAPE evidence and the snapshot from the same fit,
never two numerically-divergent fits for one fold. CI cost is split
exactly like `candidate-a-recovery`: `test_fold_refit_service.py` pays for
one tiny (draws=15/tune=15) shared-model fit in blocking CI (one real fit
total, reused via a module-scoped fixture - a first attempt at ~7
independent real fits took 28 minutes and was rejected as too slow before
landing); `test_fold_refit_service_recovery.py` (Model C, the
single-market fallback path, two real fits feeding genuine multi-fold
structural stability) runs schedule/manual-only via the new
`fold-refit-recovery` workflow job, added to `scripts/wait_for_pr_green_
then_merge.ps1`'s `-AllowedSkippedChecks`. `REQ-LEAK-001` and
`REQ-STAB-001` updated in place (their own established "Capability status"
convention) rather than superseded - this is delivery of scope both
records already described as open, not a new business decision.

**Rejected alternative:** Widening `leakage_safe_expanding_window_
backtest`'s `fit_fold_fn` contract to also receive `fold_id` (rejected -
would change an existing, separately-tested public contract's shape for
every caller, for the sole benefit of one new caller that can just
reimplement the same ~15-line selection loop from already-public
primitives instead). Fitting each fold twice, once for the existing
helper's r2/mape row and once more for a snapshot (rejected - doubles
real MCMC cost and risks two independently-seeded fits reporting
inconsistent numbers for what is nominally "the same fold").

**Impact:** `ancestry_mmm/application/fold_refit_service.py` (new),
`ancestry_mmm/tests/test_fold_refit_service.py` (new, blocking CI),
`ancestry_mmm/tests/test_fold_refit_service_recovery.py` (new,
schedule/manual-only), `.github/workflows/tests.yml` (new `fold-refit-
recovery` job; both Python 3.11/3.12 jobs now also `--ignore` the new
recovery file), `scripts/wait_for_pr_green_then_merge.ps1` (`"Fold refit
recovery"` added to `-AllowedSkippedChecks`), `docs/approved_requirements/
REQ-LEAK-001.md` and `REQ-STAB-001.md` (Capability status/Unresolved
decisions updated in place), `docs/approved_requirements/index.json`
(affected_modules/required_tests updated for both records). No change to
`core.validation_folds`, `core.structural_stability`,
`pages/06_Diagnostics.py`, or any persisted schema. Point-in-time
reconstruction of raw source data (selecting a source *version* as of a
fold's cutoff, fold-local `core.official_preparation`/`core.
frequency_conversion` re-execution) remains undelivered - Work Package 1
part 2.

**Owner:** Modelling / Platform engineering (validation pipeline).
**Status:** Implemented.

## Structural-causal authority reconciliation (Work Package 0)

**Context:** The reviewed GitHub authority document
(`docs/specification_authority.md`) recorded the earlier focused Bayesian-
validation/identification/calibration overlay (Part 3 v1.7, Part 6 v1.6,
Part 7 v1.5, Part 9 v1.5, Part 10 v1.6) but had not yet reconciled the
local PRD suite's newer structural-causal revisions. Mid-work-package, the
user supplied a refreshed local `docs/PRD/` snapshot (Part 3 bumped v1.8
-> v1.10, cumulatively retaining v1.9/v1.8 content; Part 9 v1.5 -> v1.6;
Part 10 v1.7 -> v1.8; Part 11 v1.6 -> v1.7; Part 4/6/7/8 unchanged version
labels). Part 3 v1.10 additionally resolved a previously open governance
question: PyMC is now the approved primary production MMM engine (not
`decision_required`), distinct from the still-open supplemental
structural-causal-adapter question.

**Decision:** Reconciled the newer local PRD structural-causal overlay
into repository authority as five new approved requirement records:
`REQ-ENGINE-001` (approved primary production MMM engine — zero
implementation gap, since every production model builder already runs on
PyMC and Meridian is not imported anywhere in `ancestry_mmm/**`; cross-
referenced into root `AGENTS.md`'s "Engine-capability boundary" section,
which previously left the PyMC-versus-Meridian choice open), and four
target-state-only contracts with zero implementation —
`REQ-SCENGINE-001` (structural causal engine adapter, capability
resolution, runtime isolation), `REQ-SCEFFECT-001` (posterior structural
intervention effects), `REQ-CAUSALROBUST-001` (DAG falsification, placebo/
permutation refutation, unmeasured-confounding sensitivity evidence), and
`REQ-SCCURVE-001` (structural intervention curve provenance and
planning-eligibility boundary, extending `REQ-CURVE-001`). Every
statistical/causal/UX choice the PRD's own decision registers (Part 6 §37
`MD-022`; Part 7 §48 `VL-028`/`VL-029`; Part 10 §47 `UX-031`/`UX-032`/
`UX-033`) leave open — including whether PathMC is adopted at all — was
routed to a new decision-support document,
`docs/wp_structural_causal_engine_decision_package.md`, with no candidate
chosen. `docs/specification_authority.md` gained a new "Version history:
focused structural-causal engine integration overlay" section (Part-by-
part version table plus an explicit "Known version-reference gaps"
subsection recording that Part 4/6/7/10/11 each still reference a Part 5
v1.6 not supplied locally — only Part 5 v1.4 is present) and five new
implementation-gaps-table rows. `docs/approved_requirements/index.json`
and `README.md` updated for the five new records and their `REQ-ENGINE-*`/
`REQ-SCENGINE-*`/`REQ-SCEFFECT-*`/`REQ-CAUSALROBUST-*`/`REQ-SCCURVE-*`
naming-convention prefixes.

Separately, reviewed the safe-merge script's existing Candidate-A
affected-path automatic recovery-gate mechanism
(`scripts/wait_for_pr_green_then_merge.ps1`'s `$CandidateAPaths`/
`-RequireCandidateARecovery`) against the `Fold refit recovery` job added
by PR #286 (WP1 part 1), which had no analogous automatic dispatch/require
mechanism — a future PR could alter fold-refit/validation mathematics
while the expensive recovery job stayed schedule/manual-only unless an
operator remembered to run it. Added an analogous narrow
`$FoldRefitPaths`/`-RequireFoldRefitRecovery` mechanism, scoped (via actual
import inspection, not guesswork) to `ancestry_mmm/application/
fold_refit_service.py`, `ancestry_mmm/core/validation_folds.py`, and
`ancestry_mmm/core/structural_stability.py` — the fold-refit evidence
pipeline's own three modules. Deliberately excluded the shared production
fit path those three modules call through (`model_fit_service.py`,
`models.py`, `predict.py`, `market_specific_predict.py`,
`hierarchical_model.py`, `market_specific_model.py`) from the automatic
trigger set: those files are already exercised by every PR's blocking
Python 3.11/3.12 test suite (including `test_fold_refit_service.py`'s own
tiny real fit), and including them would make the expensive schedule/
manual job fire for nearly every modelling PR, contradicting the brief's
explicit "do not blindly require the job for every PR" instruction — the
same narrow-scoping precedent `$CandidateAPaths` itself already
established (it excludes `predict.py` despite Candidate A depending on it
transitively). Added a matching `fold-refit-recovery-gate-check`
`pull_request`-only informational annotation job in
`.github/workflows/tests.yml`, mirroring `candidate-a-recovery-gate-check`,
and registered its name in the merge script's `$InformationalChecks`.

Added `ancestry_mmm/tests/test_structural_causal_authority_reconciliation.py`
(anti-drift tests verifying the five new records are indexed and correctly
classified, the decision package exists and is referenced, the version-
reconciliation table states the actual reconciled versions without
fabricating a fictitious "fully self-contained" claim, and that
`REQ-ENGINE-001`'s zero-Meridian-import claim holds).

**Rejected alternative:** Approving PathMC, an exact DSL, an exact
falsification/placebo/sensitivity method, or any threshold from PRD prose
(rejected — explicitly out of authority for this work package per its own
governing brief; every PRD decision-register item citing these was routed
to the decision package instead). Including the shared production fit
path in the automatic Fold refit recovery trigger set (rejected — see
above; would make the expensive job effectively unconditional).

**Impact:** `docs/approved_requirements/REQ-ENGINE-001.md`,
`REQ-SCENGINE-001.md`, `REQ-SCEFFECT-001.md`, `REQ-CAUSALROBUST-001.md`,
`REQ-SCCURVE-001.md` (new), `docs/approved_requirements/index.json` and
`README.md` (updated), `docs/wp_structural_causal_engine_decision_
package.md` (new), `docs/specification_authority.md` (new overlay section
plus gaps-table rows), `AGENTS.md` (root — "Engine-capability boundary"
cross-referenced to `REQ-ENGINE-001`), `ancestry_mmm/tests/
test_structural_causal_authority_reconciliation.py` (new),
`scripts/wait_for_pr_green_then_merge.ps1` (new `$FoldRefitPaths`/
`-RequireFoldRefitRecovery` automatic detection, `fold-refit-recovery-gate-
check` added to `$InformationalChecks`), `.github/workflows/tests.yml`
(new `fold-refit-recovery-gate-check` job). No `core`/`application`/
`pages` code changes — this is a documentation/governance work package;
local PRD suite under `docs/PRD/` confirmed untracked, unstaged, and
`.git/info/exclude`-protected throughout, including after the mid-task
PRD refresh.

**Owner:** Platform engineering (authority/governance), Modelling
(requirement content).
**Status:** Implemented.

## Fix Fold refit recovery/Candidate A posterior recovery dispatch verification

**Context:** Discovered while merging PR #288 (Work Package 1 part 2). PR
#288 touches `application/fold_refit_service.py`/`core/validation_
folds.py`, so `scripts/wait_for_pr_green_then_merge.ps1` correctly
auto-detected and dispatched a `workflow_dispatch` run of `Tests` so
`fold-refit-recovery` would run. That dispatched run's `Fold refit
recovery` job genuinely succeeded (verified directly via `gh run view`),
but the script's polling loop - which relies on `gh pr checks $PRNumber
--json name,state,bucket` - kept reporting it as `SKIPPED` indefinitely,
throwing "failed/cancelled/unexpectedly-skipped required check(s): Fold
refit recovery" and refusing to merge a PR whose actual recovery evidence
was green.

Root-caused by direct comparison of four data sources for the identical
head SHA: `gh pr checks` and `gh pr view --json statusCheckRollup` both
showed `SKIPPED` (from the original `pull_request`-triggered run's
always-skipped job, per that job's own `if: github.event_name ==
'schedule' || github.event_name == 'workflow_dispatch'` condition); `gh
api repos/.../commits/<sha>/check-runs` showed *two* check-runs named
"Fold refit recovery" for that SHA - the stale skipped one and the
genuinely successful dispatched one; `gh api .../commits/<sha>/check-
suites` explained why: GitHub creates a *separate* check-suite per
trigger event (`pull_request` vs `workflow_dispatch`), and this
repository has no branch-protection required-checks configuration (this
script's own header comment already documents that gap for a different
reason - the bare `gh pr merge --auto` problem), so there is no
context-name-based merge of same-named checks across suites. The PR-level
rollup this script polled only ever reflected the *first* (pull_request)
suite's result, no matter how long the dispatched run's own job kept
running or how it concluded.

**Decision:** Added `Wait-ForDispatchedRecoveryJobSuccess` to `scripts/
wait_for_pr_green_then_merge.ps1`: after dispatching, it locates the
specific dispatched run by `gh run list --event workflow_dispatch`
(filtered to the expected head SHA and a dispatch timestamp, with a 30s
clock-skew buffer), then polls that exact run by ID via `gh run view
<run-id> --json headSha,jobs`, inspecting the *named job's* own
`status`/`conclusion` - never the run's overall `conclusion` (a dispatched
`Tests` run also carries unrelated schedule-only jobs, e.g.
`Deterministic attribution recovery`, that can fail independently without
that being relevant to the job actually being verified) - and never
trusting `gh pr checks`/`statusCheckRollup` for these two check names.
Replaces the previous `-RequiredChecks`/`-AllowedSkippedChecks`
add/remove dance for both `Candidate A posterior recovery` and `Fold
refit recovery` (the same blind spot applies symmetrically to Candidate
A's dispatch path, fixed with the identical mechanism rather than a
one-off special case for fold-refit only, per explicit instruction). Both
check names remain permanently in `-AllowedSkippedChecks` (the PR-checks
view will forever show them as `skipping` from the stale pull_request-
suite entry - now a known, harmless, recognised state rather than an
enforcement signal) so the unclassified-check fail-closed guard still
recognises them.

This tooling-only fix was intentionally kept out of PR #288 itself and
merged separately against a fresh `origin/main`, so it does not itself
touch `application/fold_refit_service.py`/`core/validation_folds.py`/
`core/structural_stability.py` and therefore does not trigger the (until
this fix, broken) `Fold refit recovery` auto-require path against itself
- it merges cleanly through the existing gate, after which PR #288 is
rebased onto the fixed main and merged using the corrected script.

**Rejected alternative:** A one-time manual-verification bypass for PR
#288 specifically (rejected per explicit user decision - fixing the gate
mechanism itself is more valuable than a single documented manual
override, since the same defect would silently recur for every future PR
touching Candidate A or fold-refit-recovery paths). Trusting the dispatched
run's overall `conclusion` instead of the specific job's `conclusion`
(rejected - a dispatched `Tests` run's other schedule-only jobs, e.g.
`Deterministic attribution recovery`, can fail for reasons unrelated to
the job actually being verified, which would make the run-level
conclusion an unreliable, over-broad proxy). Fixing only the
`Fold refit recovery` path and leaving `Candidate A posterior recovery`'s
identical mechanism unfixed (rejected - same underlying bug, same fix,
per explicit instruction to check and fix both).

**Impact:** `scripts/wait_for_pr_green_then_merge.ps1` (new `Wait-
ForDispatchedRecoveryJobSuccess` function; both recovery-dispatch blocks
rewritten to call it instead of the `-RequiredChecks`/
`-AllowedSkippedChecks` dance), `ancestry_mmm/tests/
test_merge_gate_script_contract.py` (existing `test_fold_refit_recovery_
removed_from_allowed_skipped_when_required` replaced with `test_fold_
refit_recovery_verified_via_dispatched_run_not_pr_checks`, asserting the
old broken lines are gone; new `TestDispatchedRecoveryJobVerification
FixesPRChecksBlindSpot` class - 6 tests covering the helper's definition
order, run-location logic, per-job (not per-run) conclusion checking,
head-SHA guard, Candidate A symmetry, and that both check names remain
classified as allowed-skipped). No production `core`/`application`/
`pages` code changed - this is a tooling-only fix to the merge-gate
script and its own contract tests, verified against the live, real
dispatched run this defect was found in (run 32156346023, job 95774377982
- confirmed `conclusion: success` throughout the diagnosis, independent
of this fix).

**Owner:** Platform engineering (CI/merge tooling).
**Status:** Implemented.

## Fix job-visibility race in Wait-ForDispatchedRecoveryJobSuccess

**Context:** Found immediately after the previous fix (`Fix Fold refit
recovery/Candidate A posterior recovery dispatch verification`, above)
landed on `main` and was exercised for real against PR #288's actual
retry. `Wait-ForDispatchedRecoveryJobSuccess` located the freshly
dispatched run on its very first list-poll (run 32179871092), then
immediately called `gh run view <run-id> --json headSha,jobs` - which at
that instant did not yet include a `Fold refit recovery` entry in the
~17-job `Tests` workflow's `jobs` array, even though `gh api .../actions/
runs/<id>/jobs` showed the job present (along with every other job)
moments later. The helper treated "job not found in this one snapshot"
as an immediate hard failure ("Dispatched run ... has no job named ..."),
which is wrong: a run's job list can lag the run itself becoming
queryable by a few seconds, and that lag is indistinguishable from a
genuine `-FoldRefitPaths`/`-CandidateAPaths` workflow-drift case from a
single snapshot.

**Decision:** Added a 3-minute (or `-TimeoutMinutes`, if shorter) grace
window before treating "job not found" as a real failure -
`Wait-ForDispatchedRecoveryJobSuccess` now retries (`continue`, same
`-PollIntervalSeconds` cadence as every other wait in this script) while
within that window, and only throws "still has no job named ... after a
several-minute grace window" once it has elapsed without ever seeing the
job. A job that *is* found (even mid-run, not yet completed) is handled
exactly as before - the grace window only covers the "never seen it at
all yet" case, never masks a job that started and then failed.

**Rejected alternative:** A single retry immediately after locating the
run, hoping the race resolves within one extra poll (rejected - the
actual lag observed live was long enough that a fixed single retry could
plausibly still lose the race under different load conditions; a proper
grace window bounded by elapsed time, not iteration count, is the correct
fix). Increasing `-PollIntervalSeconds` globally to paper over the race
(rejected - would slow down every other polling loop in this script for
a narrow, localised timing issue).

**Impact:** `scripts/wait_for_pr_green_then_merge.ps1`
(`Wait-ForDispatchedRecoveryJobSuccess`'s "job not found" branch now
retries within a grace window instead of failing immediately),
`ancestry_mmm/tests/test_merge_gate_script_contract.py` (new
`test_helper_retries_a_not_yet_visible_job_within_a_grace_window`,
asserting the grace-check-then-retry ordering precedes the hard failure
inside the same branch). No production `core`/`application`/`pages` code
changed.

**Owner:** Platform engineering (CI/merge tooling).
**Status:** Implemented.

