# Time/segment-varying outcome valuation and joined ROI economics: gap analysis and proposed architecture

Status: analysis and architecture proposal only. No `core`, `application`, or
`pages` code accompanies this document. Every design element below that
depends on an unresolved statistical, financial, business, or governance
choice is explicitly marked **decision-bound** and traces to
`docs/wp2_outcome_valuation_decision_package.md` — nothing decision-bound is
implied to be approved by appearing in a proposal.

## Target capability (restated for traceability)

1. Family History must support a supplied projected LTR/outcome value that
   varies by week and by segment, not one constant LTR.
2. DNA must support supplied revenue/outcome value varying by week and,
   where the governed outcome structure requires it, by outcome/segment.
3. These weekly valuation series are **joined** to the MMM's incremental
   posterior outcomes — never treated as incremental outcomes themselves.
4. The resulting economics must support ROI and other value metrics by
   channel and other already-governed reporting dimensions.
5. Users must select an arbitrary reporting period and view results
   aggregated by week/month/quarter/year/total selected period.
6. A waterfall-style economic decomposition is wanted; its exact accounting
   definition must not be invented — only reconciled if already authorised.
7. Existing constant-value/LTV support must be assessed for backward
   compatibility, not simply removed.

## Method

This analysis is drawn from two full-repository research passes: (a) an
inventory of every existing outcome/value/cost/ROI/economics/persistence/
UI mechanism in `ancestry_mmm/` and every plausibly-relevant approved
`docs/approved_requirements/REQ-*` record, and (b) a targeted read of all
11 local PRD parts plus the governed-FX addendum for every passage
touching LTR/LTV, DNA revenue, ROI/CPA formulas, waterfall/decomposition,
time/segment-varying value, reporting-period aggregation, and value-FX.
Every citation below traces to a specific file:line or PRD part/section;
nothing is paraphrased from memory.

---

## 1. Gap analysis: what already exists versus the target capability

| Capability element | Exists today | Gap |
|---|---|---|
| Per-outcome value concept | `OutcomeDefinition.value_weight`/`value_currency` (`core/outcomes.py:486-487`) — one constant scalar per `outcome_id`, in `_FINGERPRINT_FIELDS` | Not week-indexed, not segment-indexed beyond the outcome_id itself |
| CPA/ROI arithmetic | Consistent `value/cost` (ROI) and `cost/outcome` (CPA) pattern across `core/canonical_curves.py:789-840`, `core/attribution.py:261-326,472-487`, `core/optimization.py:2130-2326` — 12 verbatim instances, internally consistent, never defaulting a missing weight to 0/1 | Formula is implemented but never reconciled into approved repository authority as a business definition (see §9 and `REQ-ECON-001` below) |
| Value → outcome join | Every existing formula already multiplies a *count* outcome by a *constant* weight (`value = vol * weight`) — the join pattern itself already exists | The weight is never week-varying; there is no mechanism to multiply a *week-indexed* value series against a *week-indexed* posterior draw |
| FH/DNA value distinction | `value_weight` is per `outcome_id`; FH segments (New/DNA cross-sell/Winback) and DNA segments (`DNA_SEGMENT_NEW`/`DNA_SEGMENT_EXISTING_FH`/`DNA_SEGMENT_COMBINED`, `segment_dimension` per `REQ-DATAIN-002`) are already distinct governed identifiers | No FH-vs-DNA *valuation-object* distinction exists — both would use the identical scalar `value_weight` mechanism today |
| NBT (closest existing "supplied weekly business measure") | `core/net_billthrough.py` — a governed, week-varying, long/wide, completeness-validated supplied series | NBT is explicitly a **count**, never a value/currency layer (`NBT_UNIT = "bill-through subscriber"`); AGENTS.md forbids using NBT "as ... a value layer" — so NBT's mechanism is a *structural pattern* to mirror, never a base to extend |
| Cost/spend time-variation | `core/media_costs.py`'s `piecewise_linear`/`uploaded_plan` cost-mapping methods already support time-varying spend↔delivery conversion (`REQ-SCEN-002`) | This is the cost (denominator) side only; no analogous governed object exists for the value (numerator) side |
| FX for spend | `REQ-FX-001` through `REQ-FX-006` (approved 2026-08-27, zero implementation) — full target-state architecture for spend/cost FX; `core/canonical_curves.py`'s `_currency_metadata()` already implements dated, sourced FX for curve-time spend | Architecturally distinct from, and silent on, value/revenue FX (§7 below) |
| Persistence pattern for a scalar value object | `config/value_mapping.json`, `config/currency_context.json` — project-level JSON singletons, fingerprint-verified (`core/persistence.py`) | Singleton pattern does not fit a week × segment × outcome time series; no existing pattern is reused for anything week-varying and value-shaped |
| Source-pack domain for supplied weekly data | Four fixed logical domains (`REQ-DATAIN-001`): Outcomes, Activity and Media, Context and External Factors, Experiment Evidence (optional) | A weekly valuation series is not itself an "outcome" in the modelling sense (it is a joinable multiplier) — its domain classification is undecided (§9 of decision package) |
| Reporting-period aggregation (week/month/quarter/year/custom) | Nothing. Confirmed absent in both code (`core/reporting_rollups.py`, `core/outcome_group_totals.py` aggregate by outcome-group/posterior-draw, never by calendar period) and PRD (only two fixed YoY comparison periods, `dim_comparison_period`, Part 5 §31.1; `RP-005`'s "standard periods" is an open decision item) | Full capability gap — no code, no settled PRD requirement, only an open decision item |
| Waterfall / economic decomposition | `core/attribution.py::contribution_waterfall` + `components/charts.py::create_waterfall_chart` — a **volume/contribution** waterfall only, never economic (ROI/CPA/FX/mix) | An *economic* waterfall requires a defined accounting method; PRD names required components (`REQ-FX-006` §4) but never an accounting method (§6 below) |
| Uncertainty propagation for value | Posterior-draw aggregation already governs outcome-count uncertainty (`REQ-VAL-001`, "aggregate draws before summary") | No mechanism exists for a *value multiplier's own* uncertainty (if one is ever supplied) to combine with posterior-draw uncertainty |
| Value-weight negativity guard | `OutcomeValueMapping.__post_init__` already rejects negative values "Until Finance approves negative value semantics" (`core/planning/value.py:888-891`) | Confirms the codebase already anticipates a future Finance decision on this exact class of question — precedent for how this workstream's decision items should be structured |

---

## 2. Proposed canonical weekly valuation data contract

**Status: proposal only — every field below whose content depends on an
unresolved choice is marked; the *shape* is a design option, not an
approved schema.**

Reusing existing governed identifiers wherever possible (per the task's
explicit instruction), a canonical weekly valuation record would be keyed:

```text
WeeklyOutcomeValue:
    outcome_id            # existing OutcomeDefinition identity (core.outcomes)
    market                # existing market identifier
    segment_dimension     # existing REQ-DATAIN-002 vocabulary
                          # (dna_customer_relationship | dna_purchase_recipient |
                          #  dna_activation_status | fh_customer_segment |
                          #  combined | custom | unspecified)
    week                  # existing canonical modelling week (CanonicalCalendar)
    value_per_unit        # DECISION-BOUND: what this represents for FH vs DNA (§3)
    currency              # existing ISO-3 currency vocabulary (CurrencyContext)
    value_basis           # DECISION-BOUND: mirrors PRD Part 5 dim_value_definition's
                          # value_basis/nominal_or_real/horizon/discount_rate fields —
                          # none of which exist for a *week-indexed* series today
    source                # existing ActivityDefinition/MediaInputSpec-style provenance field
    quality_status        # existing REQ-COVERAGE-001 missingness vocabulary
                          # (observed_zero | missing_expected | not_applicable |
                          #  unavailable_source | suppressed | estimated | modelled | unknown)
    schema_version
    effective_period_start / effective_period_end
```

This mirrors three existing governed-record patterns simultaneously,
deliberately, rather than inventing a fourth shape:

- **Identity/versioning/persistence contract** — from `REQ-SEARCH-001`'s
  `SearchObjectDefinition` (immutable version lineage, `schema_version`,
  quarantine-on-malformed import).
- **Weekly long/wide supplied-series shape with completeness validation**
  — from `core.net_billthrough.NetBillthroughCompletenessMetadata` (the
  only existing example of a governed, week-varying, analyst-supplied
  business series in this repository).
- **Missingness-state vocabulary** — from `REQ-COVERAGE-001`'s canonical
  eight-state vocabulary, rather than inventing a new one (per that
  record's own reusability intent).

**PRD grounding, and its limits:** Part 5 §10.4's `dim_value_definition`
(`value_definition_id, value_name, outcome_definition_id, value_basis,
currency, nominal_or_real, horizon, discount_rate [nullable], ...`) is the
closest existing PRD schema, but it is a **static, single-value-per-outcome
construct with no week-indexed or segment-indexed fact table anywhere in
the PRD suite** — confirmed by direct search, not merely unread material.
Part 5 §8.5's `bridge_outcome_relationship` additionally references a
`value_rule_id` field and a `"valuation"` relationship type, but **no PRD
document anywhere defines what a `value_rule` contains** — this is a
PRD-internal referenced-but-undefined gap (see decision package D10), not
something this analysis can safely infer. The proposed `WeeklyOutcomeValue`
shape above is this analysis's own extrapolation from adjacent approved
patterns, not a PRD-supplied schema — it must be treated as a starting
proposal for review, not a pre-approved contract.

---

## 3. Family History projected LTR versus DNA revenue: distinction

**Decision-bound in full — no PRD passage anywhere defines either.**

Confirmed facts, not assumptions: the literal term **"LTR" appears nowhere
in the codebase or the PRD suite.** The repository's own vocabulary is
`LTV`/`value_weight`/`ltv`; the PRD's is "lifetime value"/"lifetime or
portfolio value" — always a flat enumeration item alongside revenue and
contribution, never structurally distinguished from DNA revenue, and never
stated to vary by week or segment. AGENTS.md and `REQ-OUT-001` both require
that sign-up/GSA/Gross Bill Through/Bill Through/NBT/revenue/contribution/
lifetime-value remain distinct measures with no assumed conversion
sequence "unless Finance and Product have explicitly approved that
relationship" — this governs *this exact question* and forecloses
inventing an attachment.

Proposed structural distinction (decision-bound on content, not on shape):

- **FH projected LTR** is proposed to attach to one (or more, per segment)
  existing FH `outcome_id` in the New/DNA-cross-sell/Winback family —
  **which exact outcome_id(s) is decision-bound** (candidates: an existing
  GSA/sign-up outcome, the bounded-test NBT outcome under `REQ-NBT-002`, or
  a new, not-yet-defined FH outcome — AGENTS.md's "Net Bill Through must
  not be used ... as a value layer" explicitly forecloses attaching LTR
  *through* NBT's own object, though LTR could still be reported *alongside*
  an NBT-based fit).
  Part 8 §27.3's `V_portfolio = V_FH + V_DNA + V_cross-product -
  V_cannibalisation` confirms FH and DNA value streams are expected to
  combine at reporting time, but does not define either term.
- **DNA revenue** is proposed to attach to DNA kit/order outcomes, keyed by
  the existing `segment_dimension` vocabulary (`dna_customer_relationship`,
  `dna_purchase_recipient`, `dna_activation_status`) — **whether DNA
  revenue is supplied per-kit, per-order, or per-outcome-id, and whether it
  varies by all three segment axes or a subset, is decision-bound.** No
  PRD passage links DNA orders/kits to a revenue-per-kit or revenue-per-order
  figure anywhere (confirmed by direct search).

Both series are proposed to be **structurally separate `WeeklyOutcomeValue`
records** (never a shared value object across FH and DNA, mirroring
`REQ-SEARCH-003`'s precedent of keeping FH and DNA identities distinct even
when source columns are shared) — this separation itself is not
decision-bound; only each series's exact definition and attachment is.

---

## 4. Proposed join from weekly segment/outcome value to incremental posterior outcomes

**Architecture is a direct, minimal extension of the existing pattern; the
statistical treatment of week-varying inputs is decision-bound.**

Today, every existing ROI-like formula (`core/canonical_curves.py:822-826`,
`core/optimization.py:2190-2207`) computes:

```text
incremental_value = incremental_outcome_count(draw) * value_per_response[outcome_id]
```

where `value_per_response`/`ltv` is a **constant** looked up once per
`outcome_id`. The proposed join extends this to:

```text
incremental_value(draw, week) = incremental_outcome_count(draw, week)
                                 * value_per_unit[outcome_id, segment, week]
```

i.e. the multiplication step itself does not change — only the value
operand becomes week-indexed instead of scalar. This is deliberately the
smallest structural change consistent with AGENTS.md's "Mathematical
rules": "CPA and ROI must use incremental outcome counts or value, not
log-scale eta contributions" and "Posterior draws must be aggregated before
posterior summaries" — the multiplication happens at draw level, per week,
before any aggregation, exactly mirroring how `core.canonical_curves`
already computes `average_roi`/`marginal_roi` at draw level today.

**Confirmed by PRD text, not invented:** Part 4 §14.3 ("Maturity
alternatives") already articulates this exact principle generically: *"the
architecture may support ... commercial value layers applied to an earlier
approved outcome."* Part 5 §12.4 makes the reverse prohibition explicit:
*"Platform-reported conversions, CPA, ROAS and attributed revenue may be
retained for comparison and diagnostics, but they must not be represented
as the MMM incremental outcome."* Both are already-settled PRD content
(not decision-bound) and both are already implied by AGENTS.md and
`REQ-OUT-001` — no new REQ record is needed to establish the join
*principle*; see `REQ-ECON-001` below for what is formally reconciled.

**Decision-bound:** whether a week's `value_per_unit` is treated as a fixed
known constant for that week (no distributional uncertainty of its own) or
itself carries a distribution to be combined with the posterior — this is
§5's question, not resolved here.

---

## 5. Required treatment of uncertainty when values vary across weeks

**Fully decision-bound — no existing mechanism or PRD passage addresses
this.**

Two structurally distinct candidate treatments exist, framed here (not
chosen):

- **Fixed-value treatment**: each week's supplied `value_per_unit` is a
  known constant (an analyst-supplied planning assumption, not itself a
  random variable). Uncertainty in `incremental_value(draw, week)` then
  derives *only* from the existing posterior-draw uncertainty in
  `incremental_outcome_count(draw, week)`, propagated by the same
  draw-then-aggregate discipline `REQ-VAL-001`/AGENTS.md already require.
  This is the natural extension of how the existing scalar `value_weight`
  is already treated (as a fixed weight, never itself drawn).
- **Distributional-value treatment**: a supplied value series carries its
  own uncertainty (e.g. a confidence interval on projected LTR), which
  must combine with posterior-draw uncertainty — e.g. via independent
  sampling of the value distribution per draw, or via a documented
  worst/best-case sensitivity band reported alongside the point estimate.
  This is materially more complex and has no precedent anywhere in this
  repository's existing uncertainty machinery.

Whichever is chosen, the existing invariant must hold unchanged: "Posterior
draws must be aggregated before posterior summaries" and "Do not add
independently summarised medians" (AGENTS.md) — any value-side uncertainty
must enter *before* aggregation, never be bolted onto an already-summarised
point estimate. This constraint is not decision-bound; it already governs
whichever treatment is chosen.

---

## 6. Aggregation contract for arbitrary date ranges and month/quarter/year views

**Full capability gap, confirmed absent in both code and PRD; the
weighting rule for partial periods is decision-bound.**

No reporting-period aggregation control (week/month/quarter/year/custom)
exists anywhere in the application today (`core/reporting_rollups.py` and
`core/outcome_group_totals.py` aggregate by outcome-group and posterior
draw, never by calendar period; no `date_input`/`start_date`/`end_date`
control exists on any Results page). The PRD's only period-aggregation
content is the modelling-week definition itself (`dim_period_definition`,
Part 5 §6.2) and a fixed two-period YoY comparison (`dim_comparison_period`,
Part 5 §31.1) — neither is an arbitrary custom-range aggregator. The one
open decision item naming this (`RP-005`, "standard periods") is scoped to
"fiscal, model and rolling comparison periods," not a general date-range
picker.

**The closest existing precedent for partial-period weighting** is
`REQ-SCEN-002`/`core.planning.phasing`'s `calendar_day_overlap_v1` method,
which allocates a *forward-looking monthly plan* into weekly simulation
inputs with strict per-month conservation and "auditable boundary-week
attribution." This is architecturally the right pattern to mirror for
*historical reporting* roll-up (week → month/quarter/year), but it exists
today only for the opposite direction (month → week, for planning) and
covers spend/delivery, not value/economics. Reusing it would require:

- generalising the day-overlap allocation to roll **up** (week-level
  results into month/quarter/year buckets) rather than down;
- confirming whether the same `calendar_day_overlap_v1` convention should
  govern the reporting direction, or a different, decision-bound weighting
  rule is needed (proportional day-count vs. flat calendar-month share vs.
  ISO-week-based quarters, etc. — **decision-bound**, no PRD guidance
  exists for this direction).

**Architecture proposal (shape only, not approved):** a new period-
aggregation service, given an arbitrary `[start_date, end_date)` and a
target grain (`week | month | quarter | year | total`), that sums
already-computed weekly `incremental_outcome`/`incremental_value`/`spend`
rows (draws aggregated per the existing discipline) into the requested
buckets, reusing the existing outcome-group and market/channel dimensions
rather than inventing new ones. This does not require re-fitting or
re-drawing the model — it operates on already-materialised weekly
economics rows, mirroring how `core.outcome_group_totals` already
aggregates along the outcome-group dimension without touching posterior
sampling.

---

## 7. Relationship to media spend, cost mappings, and governed FX

- **Spend/cost side is unaffected.** `core.media_costs.MediaInputSpec`/
  `MediaCostMapping` govern spend↔delivery conversion only; nothing in
  this workstream changes that mechanism. `REQ-FX-001` through `REQ-FX-006`
  govern spend/cost FX and are architecturally silent on value/revenue FX.
- **Value/revenue FX is a confirmed, distinct, unaddressed question.** The
  governed-FX addendum's title and scope are spend-exclusive
  ("Historical Spend Conversion, Local-Currency Reporting and USD
  Consolidation"); every worked mechanism in it (currency-concept
  separation, conversion methods, historical-vs-future rate objects,
  scenario/optimisation treatment) is illustrated exclusively with spend
  examples. The addendum's own Section 20 Finance-decision list (10 items)
  **names zero items about revenue/value conversion** — this is not merely
  unresolved, it is absent from the list of things Finance was asked to
  resolve. The only three "value" mentions in the entire addendum (§14.1
  "local values," §19 "value and cost currencies are not silently mixed,"
  §19 "make currency explicit in value objectives") assert that value/cost
  currency separation must exist without ever defining a value-conversion
  method. Part 5's `DD-013` decision item groups "contribution and LTV
  basis" alongside FX/currency policy as a joint Finance-owned cluster,
  but does not state how they interact.
- **Existing curve-time FX mechanism is available as a precedent, not a
  ready-made answer.** `core.canonical_curves._currency_metadata()`
  already implements dated, sourced FX governance for *curve* economics
  (local/reporting currency, FX rate, `fx_source`, `fx_as_of_date`) —
  structurally the closest existing mechanism a value-FX policy could
  reuse, but it was built for spend-derived economics, not a directly
  supplied revenue/value series.
- **`_validate_no_mixed_currency_value_weights()`** (`core/optimization.py:2436`)
  already fails closed rather than silently converting when outcome_ids
  with different `value_currency` are combined — this existing fail-closed
  discipline should extend unchanged to a week-varying value series: no
  new code should quietly introduce an implicit FX conversion where none
  is currently permitted.

**Decision-bound (see decision package D7):** whether a supplied weekly
value series follows the *same* immutable historical FX-rate-set/
conversion-policy machinery `REQ-FX-002`/`REQ-FX-003` define for spend, a
separate value-specific rate policy, or Finance-pre-converted figures
supplied directly in the target reporting currency.

---

## 8. Required persistence, provenance, source-version, and stale-state behaviour

Three existing patterns are available to extend; which one (or combination)
applies is itself partly decision-bound (see decision package D9 on source
domain).

- **Singleton scalar pattern** (`config/value_mapping.json`,
  `config/currency_context.json`) — unsuitable as-is for a week × segment ×
  outcome series (would require one file per week, defeating the
  singleton's purpose), but its **fingerprint-verification-on-import**
  discipline (`ScenarioGovernanceDependencies.value_mapping_fingerprint`,
  `core/planning/value.py:289-291`) is directly reusable: a new
  `weekly_value_series_fingerprint` slot would follow the identical
  pattern.
- **NBT long/wide weekly-frame pattern** (`core.net_billthrough`) — the
  closest existing precedent for a genuinely week-varying, analyst-supplied
  business series, including completeness validation against
  `model_start_week`/`model_end_week` and per-week anchors. This is
  structurally the best-fit precedent for the new object's *persistence
  shape* (long-form `market × segment × week` or wide-form `market × week`
  with one column per governed value series).
- **Canonical curve Parquet-artifact pattern** (`core.curve_artifact`) —
  relevant if the resulting joined economics (not the raw supplied value
  series, but its *output*) are persisted as a new evaluated-artifact type,
  mirroring the existing curve-artifact's immutable creation-time snapshot
  plus separately-revalidated current-use authorization split
  (`REQ-CURVE-001`'s "Historical artifact integrity and current
  official-use authorization" — the same two-tier discipline should apply
  to any persisted valuation-joined economics artifact).

**Staleness:** a changed value series must stale every dependent fit
output, curve, scenario, and report through the existing single-path
fingerprint mechanism (`REQ-STALE-001`) — never a second, parallel
invalidation path. `ScenarioGovernanceDependencies` already has optional
fingerprint slots for the scalar `value_mapping`/`currency_context`
(`core/planning/value.py:289-291`); a week-varying series would need an
analogous slot, following the same optional-until-required pattern
`REQ-FX-*`'s zero-implementation contracts already establish.

**Decision-bound:** which of the four existing logical source-pack domains
(`REQ-DATAIN-001`: Outcomes, Activity and Media, Context and External
Factors, Experiment Evidence) a supplied weekly value series belongs to —
it is not itself a modelled "outcome," so `DOMAIN_OUTCOMES` is not an
automatic fit despite housing NBT today; classifying it elsewhere, or
introducing a fifth domain, would itself require a new approved
requirement (`REQ-DATAIN-001` fixes the domain set at three required plus
one optional).

---

## 9. Backward compatibility for existing constant-value/LTV support

**Proposal: extend, never remove.** The existing scalar
`OutcomeDefinition.value_weight`/`OutcomeValueMapping`/`ltv: Dict[str,
float]` mechanism should be treated as the **degenerate case** of a
week-varying series (a series whose value is constant across every week in
scope), not a separate code path to be deprecated:

- Every existing formula site (`core/canonical_curves.py`,
  `core/attribution.py`, `core/optimization.py`) already isolates the value
  lookup to a single expression per formula (`value_per_response[oid]`,
  `ltv[oid]`) — extending these to accept either a scalar or a
  week-indexed lookup is a narrow, localised change per site, not a
  rewrite.
- `core/schema.py`'s `ModelSpec.segment_ltv` is already documented as a
  **legacy migration field**, with `fh_outcomes_from_spec(...,
  value_weight_new=..., value_weight_existing=..., value_weight_combined=...)`
  as its forward-migration path into `OutcomeDefinition.value_weight` — the
  same migration-not-removal precedent should extend to the new
  week-varying object: a constant legacy value migrates losslessly into a
  week-varying series with one identical value at every week, never a
  breaking schema change.
- Any project without a supplied weekly value series must continue to
  behave exactly as today (constant `value_weight`, or no value/ROI at
  all, per the existing three-state `value_status` disclosure — "not
  configured" / "partial" / "complete" — which already fails closed rather
  than defaulting a missing weight to 0 or 1).

This is a design commitment, not a decision-bound item: nothing in the
target capability requires removing existing behaviour, and AGENTS.md's
general discipline against breaking persisted contracts without migration
support applies directly.

---

## 10. UI surfaces that would need changing (future work, not built now)

Listed for planning purposes only — no UI change is made by this analysis.

- **`pages/01_Data_Upload.py`** — a new supply/review workflow for a weekly
  value series, mirroring the existing NBT review/adopt/edit workflow
  (`REQ-EVENT-001`'s analogous adoption-boundary pattern: source rows never
  auto-adopt; explicit analyst review required).
- **`pages/06_Diagnostics.py`** — coverage/completeness evidence for the
  supplied value series (mirroring NBT's completeness gate), and staleness
  disclosure when the series changes.
- **`pages/07_Results_Curve_Bank.py`** — the existing `outcome_channel_summary`/
  ROAS/CPA/value-ROAS tables and the existing contribution waterfall
  selector would need a week-varying value input path and (pending §6's
  aggregation service) a period selector; the *economic* waterfall (§6 of
  the decision package) would be a new selector alongside, never replacing,
  the existing contribution waterfall.
- **`pages/08_Scenario_Planner.py`** — `value_weights_by_outcome_id`
  construction (currently one float per outcome_id, page lines ~1494-1739)
  would need a week-indexed alternative source; `ManualScenarioInput`'s
  `ltv`/`value_mapping`/`currency_context` fields would need a parallel
  week-varying field, preserving the existing scalar fields unchanged.
- **`pages/10_Channel_Media_Units.py`** or a new page — governance UI for
  the value series itself (registration, versioning), mirroring
  `REQ-SEARCH-001`'s Channel & Media Units precedent.

None of these are scoped for implementation in this package.

---

## 11. Proposed test plan (for the eventual implementation package, not this one)

Following this repository's established characterisation-then-refactor
discipline (see `docs/wp3_diagnostics_coupling_refactor_plan.md`'s
precedent of requiring characterisation tests before behavioural change):

1. **Backward-compatibility characterisation tests** — fix the current
   scalar `value_weight`/`ltv`/`OutcomeValueMapping` behaviour across
   `canonical_curves.py`, `attribution.py`, and `optimization.py` (the 12
   formula sites catalogued in this analysis) as a golden baseline *before*
   any week-varying extension is coded, so a regression in the constant
   case is caught immediately.
2. **`WeeklyOutcomeValue` contract tests** (once §2's schema is approved) —
   round-trip/versioning/quarantine-on-malformed, mirroring
   `test_search_objects.py`'s existing pattern for a comparable governed
   record.
3. **Join correctness tests** — draw-level multiplication order (value
   applied before aggregation, never after), reconciliation between a
   constant-value degenerate case and the existing scalar formulas'
   output (must match exactly, not merely approximately).
4. **Uncertainty-treatment tests** — whichever of §5's two candidates is
   approved, a test proving posterior draws are aggregated after, never
   before, the value multiplication.
5. **Aggregation-service tests** — partial-period weighting correctness
   (conservation: sum of weekly rows within a period equals the aggregated
   period total, mirroring `REQ-SCEN-002`'s existing
   `test_month_entirely_within_canonical_weeks`/
   `test_week_spanning_two_months_receives_both_allocations`-style
   conservation tests), and correctness of week/month/quarter/year/custom
   boundary resolution.
6. **FX-for-value tests** (once D7 is resolved) — no silent conversion
   where none is approved, mirroring
   `test_optimization.py`'s existing mixed-currency rejection test for
   `_validate_no_mixed_currency_value_weights`.
7. **Staleness tests** — a changed value series stales every dependent
   fit/curve/scenario/report through the single existing fingerprint path,
   mirroring `REQ-STALE-001`'s existing test suite structure.
8. **Waterfall/decomposition tests** (once D6 is resolved) — reconciliation
   of decomposition components to the total change within an approved
   tolerance, and (per PRD Part 7 §36.5) an explicit order-sensitivity
   check if a non-symmetric method is chosen.

---

## Summary of what is, and is not, resolved by this package

**Resolved by reconciliation** (see `REQ-ECON-001`): the CPA/ROI arithmetic
formula itself (`CPA = cost / incremental_outcome`, `ROI = incremental_value
/ cost`, both average and marginal), and the join principle (value applied
to, never presented as, the incremental outcome) — both are unambiguous,
internally consistent across the codebase, unchallenged anywhere in the PRD,
and already implemented; no business/statistical choice is required to
approve them.

**Decision-bound** (see `docs/wp2_outcome_valuation_decision_package.md`):
FH LTR's exact definition and outcome attachment; DNA revenue's exact
attachment to orders/kits/outcomes; missing-week imputation; future-value
extrapolation; the economic-waterfall accounting method; FX policy for
value/revenue; aggregation weighting for partial periods; treatment of
value uncertainty; the initial content of the PRD-referenced-but-undefined
`value_rule`; and the source-pack domain classification of a supplied
weekly value series. No candidate for any of these is chosen by this
document.
