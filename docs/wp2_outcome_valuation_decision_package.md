# Outcome valuation and joined-ROI decision package

Status: decision support only. No code changes accompany this package; no
candidate approach below is enabled, selected, or implemented by it.

## Why this package exists

The target capability — Family History projected LTR and DNA revenue
varying by week and segment, joined to incremental posterior outcomes to
produce ROI and other value metrics by channel and other governed
dimensions, aggregated over arbitrary reporting periods, plus a
waterfall-style economic decomposition — was analysed in full against
existing repository code, approved requirements, and the local PRD suite
(see `docs/wp2_outcome_valuation_gap_analysis.md` for the complete
evidence base). That analysis found the CPA/ROI arithmetic itself
already resolved (reconciled into `REQ-ECON-001`), but every substantive
element of the *value input* — its definition, source, timing, currency
treatment, uncertainty, and the eventual waterfall's accounting method —
either has no PRD source at all, or is an explicit open item in one or
more of the PRD's own per-part decision registers. This package collects
those items in one place, together with the exact PRD citations, so a
future work package can review and resolve them without re-deriving the
same material from scratch.

This package does not choose among any candidate below.

## D0. The ROI-definition question — resolved, not decision-bound

The task that produced this package explicitly required checking whether
ROI means `incremental_value / spend`, `(incremental_value - spend) /
spend`, or another approved definition, and creating a decision item only
if unresolved. **This one is resolved, not decision-bound:**

- Part 6 v1.11 §24.2 and Part 8 v1.6 §8.1/§8.2/§8.5 state, consistently
  and without contradiction anywhere else in the 11-part suite:
  `CPA = (approved cost scope) / (incremental approved outcome)`;
  `ROI = (incremental approved value) / (approved cost scope)`; marginal
  ROI = `ΔV / Δx`. This is a **value/cost ratio** (ROAS-style), never a
  net-of-investment `(value - cost)/cost` figure.
- The existing codebase implements exactly this ratio, consistently,
  across three independent modules (`core/canonical_curves.py:822-831`,
  `core/attribution.py:293-305`, `core/optimization.py:2190-2225`) — 12
  verbatim formula instances, none of them the net-of-investment form.
- No PRD passage anywhere states or implies the net-of-investment form;
  the second research pass searched specifically for a competing
  `(revenue - spend)/spend` formula and found none.

Because the definition is unambiguous, uncontested, and already
implemented, this is reconciled into approved authority via
`docs/approved_requirements/REQ-ECON-001.md` rather than left open here.
**What `REQ-ECON-001` does not resolve** — and what remains genuinely
open — is what the *value* operand itself is (D1-D3 below), not the
arithmetic relating it to cost.

One terminology note carried forward, not resolved: the PRD's own
formula, despite being labelled "ROI," is mathematically identical to what
marketing practice usually calls ROAS (return on ad spend), not the
finance convention of net return on investment. `REQ-ECON-001` reconciles
the PRD's formula under the PRD's own name; whether the eventual UI/report
labelling should say "ROI" or "ROAS" (or both, distinctly) is folded into
D6 (waterfall/decomposition labelling) and D11 (reporting-period/YoY
labelling) below, since it is a presentation question, not an arithmetic
one.

## The PRD's own decision registers already flag the remaining items as open

- **Part 1, §13, item 4:** *"Revenue, contribution and lifetime-value
  definitions and cash-flow treatment."*
- **Part 1, §13, item 22:** *"Default optimisation objective and
  commercial value basis."*
- **Part 1, §13, item 36:** *"Group reporting currency, market reporting
  currencies, authoritative historical FX source, weekly conversion
  policy, future budget-rate policy and constant-currency basis."*
- **Part 2, §26, item 5:** *"Revenue, contribution and lifetime-value
  definitions."*
- **Part 2, §26, item 18:** *"Approved cost and value sources."*
- **Part 3, §29, item 13:** *"Approved media-cost, FX and value
  assumptions."*
- **Part 3, §29, item 18 / Part 7 `VL-019` / Part 9 `RP-013` / Part 11
  `API-018`:** four independently-worded copies of the same open
  question — *"YoY decomposition method and exact weekly boundaries"* /
  *"Approve components, method and tolerance"* — no part states these
  four are the same decision or which is authoritative; treated here as
  one consolidated item (D6/D11 below).
- **Part 5, §39, `DD-013` (governed currency, FX and value reporting):**
  Finance must confirm, among other FX items, *"nominal versus real
  reporting; contribution and LTV basis"* — the only place the PRD groups
  LTV basis with FX policy as a joint Finance-owned cluster, without
  stating how they interact.
- **Part 6, §37, `MD-018` (economic objective):** *"Approve default
  outcome, value and cost scope for planning."*
- **Part 6, §37, `MD-019` (NBT economics):** *"Approve short-term,
  long-term and total cost-per-NBT definitions."*
- **Part 6, §37, `MD-011` (DNA halo):** *"Approve pathway, mediator,
  segment, horizon and evidence standard."*
- **Part 8, §41, `PL-015` (downstream objective):** *"Approve outcome
  definition and completeness/maturity/value method."*
- **Part 8, §41, `PL-007` (DNA portfolio objective):** *"Approve direct
  DNA and FH halo combination."*
- **Part 8, §41, `PL-016` (marginal cap metric):** *"Approve outcome,
  value, CPA-equivalent or combined reporting."*
- **Part 8, §41, `PL-021` (whole-plan economics):** *"Approve when
  whole-plan CPA and ROI are available or suppressed."*
- **Part 9, §48, `RP-007` (downstream reporting):** *"Approve the NBT
  definition and supplied-completeness contract, and any separate
  maturity/value workflow."*
- **Part 9, §48, `RP-005` (standard periods):** *"Approve fiscal, model
  and rolling comparison periods."*
- **Part 9, §48, `RP-009` (marginal cap reporting):** *"Approve outcome
  and value units and intended audience."*
- **FX addendum, §20 (10 numbered Finance-decision items):** none names
  revenue/value conversion — a confirmed absence, not an oversight (see
  D7 below).

## Decision required

### D1. Family History projected LTR: definition and outcome attachment (`DD-013`, Part 1 item 4, Part 2 item 5, Part 6 `MD-018`/`MD-019`, Part 8 `PL-015`)

Approve what "projected LTR" means for Family History, which existing FH
`outcome_id`(s) it attaches to, and whether it varies by all three FH
segments (New, DNA cross-sell, Winback) or a subset.

**Candidate D1-A — LTR attaches to the existing bounded-test NBT
outcome family, reported alongside it (never replacing it as the fitted
outcome).** Reuses `REQ-NBT-002`'s existing per-segment outcome_ids
(`fh_net_billthrough_count_new/_dna_cross_sell/_winback`) as the join
target. Requires resolving the tension AGENTS.md already flags: NBT "must
not be used ... as a value layer" — this candidate must join LTR *to*
the NBT count, not redefine NBT *as* a value.

**Candidate D1-B — LTR attaches to GSA/sign-up instead of NBT.** Avoids
touching NBT's non-value-layer constraint entirely; requires its own
governance decision about which FH acquisition event LTR is meant to
value.

**Candidate D1-C — a new, not-yet-defined FH outcome is created
specifically to host LTR.** Most flexible; requires the full new-outcome
approval chain (`REQ-OUT-001`/`REQ-OUT-002`) before any value can attach.

This package does not choose among D1-A/D1-B/D1-C, nor any per-segment
variation policy within whichever is chosen.

### D2. DNA revenue: attachment to orders/kits/outcomes (`DD-013`, Part 1 item 4, Part 6 `MD-011`, Part 8 `PL-007`)

Approve how DNA revenue attaches to DNA kit sales/orders, and which of the
existing `segment_dimension` axes (`dna_customer_relationship`,
`dna_purchase_recipient`, `dna_activation_status`) it varies by.

**Candidate D2-A — per-kit revenue, varying by week and
`dna_customer_relationship` only.** Simplest; may understate variation
if activation status or recipient type materially affects realised
revenue.

**Candidate D2-B — per-kit revenue varying by all three segment axes
where data supports it, degenerate (constant) elsewhere.** More
faithful to real variation; requires more granular supplied data than
may exist.

This package does not choose between D2-A/D2-B, nor any DNA-halo
combination rule (`MD-011`/`PL-007` remain their own open items,
predating and broader than this package).

### D3. Missing-week imputation policy (no PRD guidance found)

Approve what happens when a supplied weekly value series has a gap for
one or more weeks within the model/reporting window.

**Candidate D3-A — fail closed; a gap blocks any economics for the
affected week(s), never estimated.** Mirrors `REQ-SEARCH-003`'s
"missing spend is not zero-filled from zero clicks" precedent and
`REQ-COVERAGE-001`'s canonical `missing_expected` state.

**Candidate D3-B — carry-forward or interpolate under an explicit,
governed, versioned imputation method, disclosed per week.** More
usable; requires approving a specific interpolation method and its
disclosure contract, neither of which any existing record supplies.

This package does not choose between D3-A/D3-B, nor any specific
interpolation method.

### D4. Future-value extrapolation policy (no PRD guidance found)

Approve how a value series is extrapolated beyond its last supplied week
for forward-looking planning/scenario use (as distinct from historical
reporting, which never needs extrapolation).

**Candidate D4-A — no extrapolation; planning/scenario use requires an
explicit, analyst-supplied future value for every planned week, never a
carried-forward default.** Consistent with `REQ-PLAN-001`'s "no silent
default" discipline.

**Candidate D4-B — an approved, versioned extrapolation method (e.g.
last-known-value carry-forward, trend extrapolation) with mandatory
disclosure of which weeks are extrapolated versus supplied.**

This package does not choose between D4-A/D4-B.

### D5. Economic-waterfall accounting method (`REQ-FX-006` §4, Part 9 §10.2/§9.4, Part 7 `VL-019`/§36.5, Part 2 §8.3, Part 3 `FR-YOY-001`-`010`, Part 4 §18.2, Part 1 §5.9)

**What is already approved:** `REQ-FX-006` §4 names a closed, approved
component list for a year-on-year CPA/ROI decomposition — "underlying
response/effectiveness, spend/saturation, channel/product/segment mix,
timing/carryover, promotions/price, capacity, external conditions, and
definition change," with FX translation as its own explicit, separately
attributed component. The PRD (Part 2 §8.3, Part 3 `FR-YOY-001`-`010`,
Part 4 §18.2, Part 7 §36.2) independently corroborates an overlapping
component set for the same class of decomposition. **What is not
approved:** the exact computation/allocation method between components,
the reconciliation tolerance, and — critically — Part 7 §36.5's own
flagged concern: *"Where decomposition depends on ordering, use an
approved symmetric or Shapley-style method or report order sensitivity"*
— no method is chosen. Separately, the codebase's only existing
"waterfall" (`core.attribution.contribution_waterfall`) is a
volume/contribution decomposition, never an economic one — an economic
waterfall would be a new artefact, not an extension of the existing one.

**Candidate D5-A — order-independent (Shapley-style) allocation.**
Satisfies Part 7 §36.5's preference directly; computationally more
expensive and less intuitive to present as a simple sequential bridge.

**Candidate D5-B — a fixed, approved sequential order, with order
sensitivity disclosed per Part 7 §36.5's fallback option.** Simpler to
compute and present as a classic waterfall chart; requires approving and
justifying one specific ordering.

**Candidate D5-C — disclose all components' marginal contribution without
forcing reconciliation to a single ordered bridge, following the
`REQ-CAP-001`/`REQ-CALIB-001` precedent of "disclose evidence, no invented
verdict."** Avoids the ordering problem entirely by not presenting a
single waterfall chart; may not satisfy the specific "waterfall-style"
visual the task requested.

This package does not choose among D5-A/D5-B/D5-C, nor any reconciliation
tolerance.

### D6. Reporting-period aggregation weighting for partial periods (`RP-005`, no PRD guidance for the reporting direction)

Approve the weighting rule when a user-selected date range or a
month/quarter/year bucket does not align exactly with the model's
canonical weeks (e.g. a month that starts mid-week).

**Candidate D6-A — reuse `REQ-SCEN-002`'s existing
`calendar_day_overlap_v1` day-overlap convention, generalised to the
reporting (roll-up) direction.** Reuses an already-approved, already-
tested method rather than inventing a new one; requires confirming the
same convention is appropriate for aggregating *already-computed* weekly
results rather than *allocating* a plan.

**Candidate D6-B — whole-week-only bucketing (a week belongs entirely to
whichever period contains its majority, or its start, or its end,
per an approved tie-break rule), no fractional splitting.** Simpler;
loses some precision at period boundaries.

This package does not choose between D6-A/D6-B, nor any tie-break rule.

### D7. FX policy for value/revenue, distinct from spend FX (`DD-013`, FX addendum §14.1/§19, confirmed absent from FX addendum §20's 10-item list)

Approve whether a supplied weekly value/revenue series follows the same
immutable historical FX-rate-set/conversion-policy machinery
`REQ-FX-002`/`REQ-FX-003` define for spend, a separate value-specific rate
policy, or is supplied already-converted by Finance in the target
reporting currency.

**Candidate D7-A — value/revenue reuses the identical `REQ-FX-002`/
`REQ-FX-003` historical rate-set and conversion-method machinery already
approved for spend.** Minimises new architecture; requires confirming
Finance actually wants the same conversion-method vocabulary
(`observed_daily`, `daily_spend_weighted_weekly_average`, etc. — note the
existing vocabulary's own naming is spend-oriented) applied to a value
series.

**Candidate D7-B — value/revenue is always supplied pre-converted to the
target reporting currency by Finance; no in-application FX conversion is
ever applied to a value series.** Avoids extending spend-shaped FX
vocabulary to a different kind of quantity; shifts the conversion
responsibility outside the application entirely.

This package does not choose between D7-A/D7-B. Either way,
`_validate_no_mixed_currency_value_weights()`'s existing fail-closed
discipline (`core/optimization.py:2436`) must continue to reject a
silent implicit conversion — this constraint is not itself decision-bound.

### D8. Treatment of value uncertainty (no PRD or code precedent)

See `docs/wp2_outcome_valuation_gap_analysis.md` §5 for the full framing.
Two candidates: **D8-A**, fixed-value treatment (uncertainty derives only
from posterior-draw uncertainty in the outcome count); **D8-B**,
distributional-value treatment (the supplied value series itself carries
uncertainty, combined with posterior draws). This package does not choose
between them.

### D9. Source-pack domain classification and initial `value_rule` content (`REQ-DATAIN-001`'s fixed four-domain set; Part 5 §8.5's undefined `value_rule_id`)

Approve which of the four existing logical source-pack domains a supplied
weekly value series belongs to, or whether a new domain requires its own
approved requirement; and, separately, approve the initial content of a
`value_rule` object, which Part 5 §8.5 references (`bridge_outcome_
relationship.value_rule_id`, relationship_type including `"valuation"`)
but never defines anywhere in the PRD suite — a PRD-internal
referenced-but-undefined gap, confirmed by direct search, not merely
unread material.

**Candidate D9-A — classify under `DOMAIN_OUTCOMES`, alongside NBT.**
Reuses the domain that already hosts the closest existing analog
(NBT's weekly supplied series); risks conflating "an outcome the model
fits" with "a multiplier joined to an outcome," which are different
things under `REQ-DATAIN-001`'s own definition of that domain.

**Candidate D9-B — classify under a new, separately-approved fifth
domain (e.g. "Valuation" or "Economics").** Cleaner conceptually;
requires its own `REQ-DATAIN-*`-style approval, since `REQ-DATAIN-001`
currently fixes the domain set at three required plus one optional.

This package does not choose between D9-A/D9-B, nor define `value_rule`'s
content.

### D10. Standard reporting periods and consolidated YoY decomposition method (`RP-005`, and the four-ID duplicate noted above: Part 3 item 18, `VL-019`, `RP-013`, `API-018`)

Approve the standard reporting-period set (fiscal/model/rolling, per
`RP-005`) the new arbitrary-date-range/month/quarter/year aggregation
should offer as presets alongside true custom ranges, and confirm that
resolving the YoY decomposition method (D5 above) resolves all four
independently-worded PRD copies of the same question, or whether they are
in fact four distinct decisions the PRD suite never actually reconciled
with each other.

This package does not choose a standard-period set, and does not assert
that the four IDs are or are not the same decision — that determination
is itself left to the reviewer.

## What this package does not decide

- Every item D1 through D10 above.
- The ROI/CPA arithmetic formula itself — that is resolved, not
  decision-bound (see D0 and `REQ-ECON-001`).
- Whether this capability is scheduled ahead of, or behind, any other
  open work-package item — this package only supplies the missing
  decision-support document.
- Any `core`, `application`, or `pages` code change — none accompanies
  this package.

## Owner and status

**Owner:** Product/Finance (LTR and DNA-revenue definitions, FX-for-value
policy, waterfall labelling), Modelling (imputation, extrapolation,
uncertainty treatment, aggregation weighting), Platform engineering
(source-domain classification, architecture once decisions land).

**Status:** Decision-support package only. `docs/wp2_outcome_valuation_
gap_analysis.md`'s proposed architecture remains a proposal pending review
of this package. `REQ-ECON-001` is unaffected by this package's open
items — it is fully resolved on its own, narrower scope.
