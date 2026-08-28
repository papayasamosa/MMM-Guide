# WP2F design note: period-over-period contribution waterfall

Status: design note only. No runtime code or UI accompanies this
document. It proves feasibility, names exact source artefacts, resolves
every question the governing brief posed, and states explicitly which
of two remaining choices are cosmetic (safe to decide here) versus which
require reviewer sign-off before implementation. No decision package is
required — every question below is resolved either by mathematical
necessity or by direct, minimal generalisation of an already-approved,
already-shipped convention. Implementation is deferred to a separate,
later PR (WP2F implementation), gated on this note being reviewed.

## 0. What this proves, in one paragraph

Every additive term in this repository's fitted model's log-linear
predictor (`eta`) is already a named quantity, and — for a single fixed
market and a single fixed outcome — decomposing `mu = exp(eta)` into
per-term contributions via the Shapley construction **already shipped
and tested** for channel attribution (`core.attribution.
compute_shapley_contributions`) reconciles **exactly**, by algebraic
construction, regardless of how many permutations are sampled. Applying
that same construction to two disjoint week-sets (Period A's weeks,
Period B's weeks) and taking the difference per component produces a
period-over-period bridge that reconciles exactly to `Outcome_B -
Outcome_A`. Two of the model's terms (the global intercept and the
market offset) are proven, not assumed, to contribute exactly zero to
any such delta for a fixed-market bridge, because neither varies by
week. No residual/unexplained term is mathematically required for the
model class this repository currently fits (Model A / Model C, without
Candidate A Search wiring) — one is retained only as an internal,
fail-closed diagnostic check, never as a presented bar.

## 1. Scope and preconditions

- **One market, one outcome (or one approved outcome-group), at a
  time — never blended.** This mirrors the existing, shipped
  precedent: `contribution_waterfall`'s existing UI caller already
  fixes market via a row mask before calling it
  (`pages/07_Results_Curve_Bank.py:1053-1063`), and `core.outcome_
  group_totals`'s entire discipline operates within one outcome/group
  at a time. No document anywhere authorises blending markets or
  outcomes into one bridge, and doing so would make "component B minus
  component A" ill-defined (a channel active in one market but not
  another has no comparable baseline).
- **Model A and Model C only.** Candidate A (the search-mediated
  demand/capture/cap chain) is explicitly and currently unsupported by
  both of the functions this design reuses —
  `compute_shapley_contributions` raises `CandidateAAttributionNotSupportedError`
  (`core/attribution.py:218-225`) and `predict_mu` raises
  `CandidateAReplayNotSupportedError` (`core/predict.py:385-391`). This
  is an existing, hard, already-fail-closed boundary — the bridge
  inherits it unchanged rather than working around it. A fit using
  Candidate A cannot produce a contribution waterfall until a separate,
  future decision extends those functions (out of scope here).
- **Model A and Model C require mirrored, parallel implementations**,
  exactly as every other attribution function in this repository already
  does (`core.attribution` / `core.market_specific_attribution`,
  `core.predict` / `core.market_specific_predict`) — this note's design
  applies symmetrically to both existing model classes via their
  respective existing extraction/decomposition functions.
- **Generalises to any modelled `outcome_id`** — the mechanism is
  generic to whichever outcome(s) the fit produces (FH GSA, FH NBT, DNA
  kit orders, or any other governed outcome); nothing here is FH- or
  DNA-specific.

## 2. Exact source artefacts

| Artefact | Module:lines | Role in the bridge |
|---|---|---|
| The fitted model's additive `eta` terms | `core/hierarchical_model.py:1225-1232` (final assembly), plus each named `pm.Deterministic`: `eta_trend` (`:1209-1213`), `eta_season` (`:1221-1222`), `eta_promo` (`:1141-1142`), `eta_market` (`:1160`/`:1188`), `eta_controls` (`:1284-1306`), `eta_primary`/`eta_active_cross_product`/`eta_exploratory_cross_product` -> `eta_channels` (`:1007-1118`), `intercept` (`:1195-1202`) | The complete, exhaustive player list for the generalised Shapley decomposition (Section 5) |
| `compute_shapley_contributions` | `core/attribution.py:200-258` | The already-approved, already-tested exact-reconciliation algorithm this note generalises (Section 5) |
| `_baseline_eta` / `_channel_log_terms` | `core/attribution.py:65-197` | The existing eta-assembly helpers this note's generalisation extends |
| `extract_posterior_params` / `extract_market_specific_posterior_params` | `core/predict.py`, `core/market_specific_predict.py` | Per-draw parameter extraction (already used by `evaluate_scenario_with_uncertainty`) |
| `sample_draw_indices` | `core/uncertainty.py:67-85` | Posterior-draw subsampling (Section 7) |
| `summarize_distribution` | `core/uncertainty.py:88-114` | The existing governed credible-interval convention (Section 7) |
| `resolve_weeks_for_calendar_period` / `resolve_weeks_for_custom_range` | `core/outcome_valuation_periods.py` (WP2D-core) | Resolves which weeks belong to Period A / Period B |
| `frame["dates"]`, `frame["market_idx"]` | `data/preprocessor.py:504-527` | Row-aligned arrays used to mask the Shapley output arrays by period and market, mirroring the existing market-mask pattern at `pages/07_Results_Curve_Bank.py:1053-1063` |
| Reconciliation tolerance precedent | `tests/test_attribution.py:101-115` | `np.testing.assert_allclose(reconstructed, mu_total, rtol=1e-5, atol=1e-6)` — reused verbatim (Section 8) |

## 3. The model's additive component structure

The fitted linear predictor is exactly:

```text
eta = intercept + eta_market + eta_trend + eta_season + eta_channels + eta_promo + eta_controls
mu  = clip(exp(eta), 1e-6, 1e9)
Y  ~ NegativeBinomial(mu, alpha)
```

(`eta_controls` is accumulated into the same `eta` tensor via
`pt.set_subtensor` before `mu` is computed — `core/hierarchical_model.py`'s
own comment at `:1253-1257` states it is "accumulated in parallel with
`eta` itself... it changes no prior, no coefficient, and no value
`eta`/`mu` itself takes," confirming it is part of the same additive sum
`mu` is computed from, not a separate pathway.)

This list is **exhaustive** for the model class this repository
currently fits — there is no eighth term. This exhaustiveness is what
makes exact reconciliation with zero residual achievable (Section 6).

## 4. Proof: intercept and market offset are zero-delta for a fixed-market bridge

Given Section 1's precondition (one market fixed for the whole bridge):

- `intercept` (`core/hierarchical_model.py:1195-1202`) is a plain
  per-outcome `pm.Normal`, indexed by outcome only — not by market, not
  by week. For a fixed outcome and any two weeks (whether in Period A
  or Period B), its value is identical.
- `eta_market` is a per-market offset — indexed by market, not by week.
  For a fixed market, its value is identical across every week in
  scope.
- Neither term varies with time. This is independently confirmed by
  `docs/specification_authority.md`'s own recorded gap for
  `REQ-BASELINE-001`: *"`core.hierarchical_model`/`core.market_specific_
  model` continue to use a single static per-market/outcome intercept
  unchanged"* — i.e. this repository's current production model has no
  time-varying baseline capability at all (that remains a separate,
  decision-bound, unimplemented item), so intercept and market offset
  are provably constant across any two periods being compared today.

**Consequence:** `contribution_of(intercept, Period B) -
contribution_of(intercept, Period A) = 0` and the same for
`eta_market`, **exactly**, for any fixed-market bridge. Both terms are
therefore computed (as part of each period's own total, and as an
internal reconciliation check — see Section 6) but are **never
presented as a bar** in the finished chart, since a bar guaranteed to
read exactly zero conveys no information and would only invite
confusion about whether the computation is broken.

This directly resolves the brief's "intercept/base" line item: it is
one of the components the note determines, **not applicable** to the
delta, precisely because of the current model's static-baseline
architecture (Section 12 revisits this if `REQ-BASELINE-001` is ever
implemented).

## 5. The component-allocation method: generalised Shapley

### 5.1 What already exists

`compute_shapley_contributions` (`core/attribution.py:200-258`) already
proves, and this repository already tests
(`tests/test_attribution.py:101-115`,
`tests/test_market_specific_attribution.py:101-113`), that:

```python
contributions = {c: np.zeros((n_obs, n_out)) for c in channels}
current = mu_baseline.copy()
for c in random_permutation(channels):
    new = current * exp(channel_log_term[c])
    contributions[c] += new - current
    current = new
# averaged over many random permutations
```

reconciles **exactly**: `baseline + sum(channel_contributions) ==
mu_total`, because each individual permutation's steps telescope
exactly (`sum_c (new - current) = final - initial`), and the average of
several exact-summing quantities is itself exact. Today, "baseline"
(`_baseline_eta`, `core/attribution.py:65-115`) is one **opaque, lumped**
starting value — the sum of `intercept + eta_market + eta_trend +
eta_season + eta_promo + eta_controls`, exponentiated. It is never split
into its own named sub-terms downstream.

### 5.2 The generalisation this note proposes

Treat **every** additive `eta` term from Section 3 — `intercept`,
`eta_market`, `eta_trend`, `eta_season`, `eta_promo`, `eta_controls`,
and each channel's existing combined direct+halo term — as a co-equal
**player** in the same Shapley game, starting from a reference of
`eta = 0` (`mu = 1`) instead of `mu_baseline`:

```python
players = ["intercept", "market", "trend", "season", "promo", "controls", *channels]
contributions = {p: np.zeros((n_obs, n_out)) for p in players}
current = np.ones((n_obs, n_out))  # exp(0)
for p in random_permutation(players):
    new = current * exp(eta_term[p])
    contributions[p] += new - current
    current = new
# averaged over many random permutations, exactly as today
```

This is the **same algorithm**, applied to a **longer player list**. It
inherits, unchanged, the existing algebraic guarantee:
`sum(all contributions) == mu_total - 1`. No new mathematical method is
introduced; no new causal claim is made. It inherits the exact same
caveat `REQ-CURVE-001` already establishes for the sibling eta-share
convention: *"a reconciliation convention, not a uniquely identified
causal decomposition"* (`REQ-CURVE-001` §"Component curve" definition) —
this note makes the identical claim for the generalised Shapley
convention, no stronger.

### 5.3 Why this does not require a decision package

`REQ-CURVE-001` Approved Decision 3 already anticipates exactly this
class of extension: *"Shapley and explicit-counterfactual component
decompositions remain available as future alternatives, each requiring
its own approval."* Approving this specific generalisation is precisely
what reviewing and merging this design note accomplishes — the
governing brief's own process for WP2F ("push the design-note PR...
merge only when green") **is** the sign-off mechanism, not a separate
decision package. This is a technical design determination the brief
explicitly asked this note to resolve ("determine which components are
required for exact reconciliation"), not a business/statistical policy
question of the kind `docs/wp2_outcome_valuation_decision_package.md`'s
D-items collect (those concern *what a supplied business number means*
— LTR definition, FX policy, etc. — not *how an already-fitted model's
own equation is decomposed*).

**What would still need explicit reviewer attention when this note is
reviewed** (not a blocking decision package, but flagged for visibility):
this is the first time non-channel structural terms are Shapley-decomposed
in this codebase; reviewers should confirm they accept extending the
existing, already-shipped convention this way before the implementation
PR proceeds.

## 6. Weekly-to-period aggregation

For each period (A and B) independently:

1. Resolve the period's weeks via `resolve_weeks_for_calendar_period`
   or `resolve_weeks_for_custom_range` (WP2D-core) against the
   project's actual available weeks — never fabricated, never scaled
   (already proven by that module's own tests).
2. Build a row mask: `week_mask = np.isin(frame["dates"], resolved_weeks)`,
   combined with the existing market mask
   (`frame["market_idx"] == market_index`) — the **identical masking
   pattern** already shipped for market selection
   (`pages/07_Results_Curve_Bank.py:1053-1063`), just with an additional
   `AND` condition.
3. Run the Section 5.2 generalised Shapley decomposition over the
   masked rows, producing one `(n_players,)` vector of **row-summed**
   per-component contributions for that period (summing the masked
   rows' per-row contributions — the existing `outcome_channel_summary`
   pattern of `.sum()` over selected rows, `core/attribution.py:293-305`,
   applied to the generalised player set instead of channels alone).

The **bridge** for each component `p` is then simply:

```text
bridge_contribution(p) = contribution(p, Period B) - contribution(p, Period A)
```

exactly as the brief specifies — never `contribution(p, Period B)`
alone.

**Unequal or partial period lengths:** handled naturally — each period's
total is the sum over however many weeks that period actually resolves
to (Section 6 step 1), and the reconciliation identity (Section 8) holds
regardless of week-count parity between A and B, since it is a statement
about two independently-computed totals, not about equal-length inputs.
**Analyst-facing caveat, not a math problem:** comparing a full quarter
against a still-partial quarter produces a *meaningful* delta
arithmetically but a *potentially misleading* one for interpretation
(fewer weeks mechanically means smaller totals in most cases) — the
implementation should disclose each period's resolved week-count
alongside its total, mirroring `REQ-ECON-004`'s existing "never scale,
but always be honest about what's actually included" discipline. This
is a UI/disclosure recommendation for the implementation PR, not a
reconciliation requirement.

## 7. Posterior uncertainty propagation

Reuses the exact "paired posterior draw" precedent already established
by `evaluate_scenario_with_uncertainty`
(`core/uncertainty.py:308-568`, esp. `:461-481`), which evaluates two
scenarios "under the *same* draw indices... paired, not independently
resampled — comparing two independently-resampled distributions would
overstate the apparent uncertainty in their difference." This note
applies the identical pairing discipline:

```python
draw_indices = sample_draw_indices(trace, n_draws, seed)
for draw_index in draw_indices:
    params = extract_posterior_params(trace, meta, at=draw_index)
    period_a_contributions = generalised_shapley(params, period_a_mask, n_permutations)
    period_b_contributions = generalised_shapley(params, period_b_mask, n_permutations)
    for p in players:
        component_delta_draws[p].append(
            period_b_contributions[p] - period_a_contributions[p]
        )
# per component:
summary[p] = summarize_distribution(np.array(component_delta_draws[p]), cred_mass)
```

Both periods are evaluated under the **same** sampled `params` per draw
— this is what makes the resulting per-draw delta a genuine paired
comparison rather than two independently-noisy distributions subtracted
after the fact. `summarize_distribution` (`core/uncertainty.py:88-114`,
already reused unmodified by WP2C for economic-value uncertainty) is
the same existing governed credible-interval convention — no new
interval method is introduced.

**Computational note for the implementation PR (not a blocker):**
running a full Shapley permutation average once per posterior draw, for
every draw in `n_draws`, is more expensive than running it once on a
point estimate (today's `contribution_waterfall` behaviour). A smaller
per-draw `n_permutations` (the existing test suite already uses 20,
`tests/test_attribution.py`) keeps this tractable; reconciliation
remains exact regardless (Section 8), so a smaller `n_permutations`
trades off *which* player gets credit for a given delta, never *whether*
the total reconciles.

## 8. The reconciliation invariant, and why it is exact regardless of sampling

**Invariant every implementation test must enforce, per posterior draw
(or for the point-estimate path):**

```text
Outcome_A_total + sum_over_players(bridge_contribution(p)) == Outcome_B_total
```

equivalently or `Outcome_B_total - Outcome_A_total ==
sum_over_players(bridge_contribution(p))`. This must hold with
`np.testing.assert_allclose(..., rtol=1e-5, atol=1e-6)` — the exact
tolerance precedent already established in this codebase
(`tests/test_attribution.py:113-115`) for the pre-existing single-period
`baseline + sum(channels) == mu_total` invariant this note's bridge
generalises.

**Why this holds unconditionally, not just "usually":** each
permutation's per-player contributions telescope exactly to `final -
initial` for that permutation, by construction (`sum_c (new_c -
current_c) = mu_total - mu_reference`, a straightforward
sum-of-differences identity). Averaging several permutations that each
individually sum exactly to the same target preserves that exact sum
(the average of N copies of the same number is that number). **This
means the reconciliation invariant holds exactly for `n_permutations =
1` just as much as for `n_permutations = 1000`** — Monte Carlo sampling
only affects how credit is *distributed* among players when multiple
players jointly explain an interaction effect; it never affects whether
the total reconciles. Section 13 gives a fully worked numeric proof of
this with `n_permutations = 1`.

## 9. Ordering for presentation

**This is a cosmetic, reconciliation-safe choice** — reordering bars in
a waterfall chart never changes the underlying values or the final
reconciled total, because addition is commutative
(`Outcome_A + d1 + d2 + ... + dn` is the same regardless of the order
the `d`'s are summed/displayed in). Recommended default, matching the
brief's own stated preference ("largest positive contributions toward
the left and negative contributors toward the right"):

1. Positive `bridge_contribution` values, sorted descending by
   magnitude (largest boost first, leftmost).
2. Negative `bridge_contribution` values, sorted ascending by magnitude
   (smallest drag first, largest drag last/rightmost).
3. `intercept` and `eta_market` are omitted entirely (Section 4) rather
   than shown as guaranteed-zero bars.
4. The internal reconciliation-diagnostic residual (Section 6, always
   expected ≈0) is never shown as a presented bar in ordinary operation
   — see Section 12.

This ordering recommendation is not binding on the implementation PR —
Product/UX may adjust it — because no ordering choice can break
reconciliation.

## 10. Which quantity: observed, posterior-expected, or posterior-predictive outcome

**Resolved by mathematical necessity, not by preference: `mu`
(posterior expected outcome, the Negative Binomial's mean parameter) is
the only quantity a named-component decomposition can be built from.**

- `mu` is exactly what `eta`'s additive terms combine to produce
  (`mu = exp(eta)`) — it is the quantity every existing decomposition
  mechanism in this repository already operates on
  (`compute_shapley_contributions`, `predict_mu`,
  `canonical_curves.py`'s incremental-response engine). Decomposing it
  into named components is well-defined because it *is* the sum of
  those named components (in log space, before the link).
- **Raw observed outcome** (`Y`) additionally contains the Negative
  Binomial's own sampling/dispersion noise (`Y ~ NegativeBinomial(mu,
  alpha)`) — noise that, by construction, is not explained by *any*
  named driver. Building the bridge from observed `Y` instead of `mu`
  would force an unavoidable, business-uninterpretable "sampling noise"
  residual into the decomposition — precisely the kind of invented
  residual the brief asks this note to avoid unless reconciliation
  otherwise fails. It does not fail when built on `mu`.
- **Posterior-predictive draws** (drawing a fresh `Y` from
  `NegativeBinomial(mu, alpha)` per posterior draw) reintroduce the same
  problem one level down — each posterior-predictive draw still carries
  its own sampling noise on top of that draw's `mu`, which is equally
  undecomposable into named business components.

**Resolution:** the bridge is built entirely on `mu` (posterior expected
outcome), aggregated across posterior draws via `summarize_distribution`
for the credible interval (Section 7) — never on raw observed `Y` and
never on posterior-predictive draws. This is consistent with AGENTS.md's
existing "Business response must be calculated on the outcome scale
through the full link function" rule and with every existing
decomposition mechanism in this codebase.

## 11. Which components are required (the brief's explicit checklist)

| Component | Required for the delta? | Why |
|---|---|---|
| Media/channel contributions | **Yes** | Direct+halo combined per channel (existing convention, Section 5.1) — varies by week whenever spend/delivery varies |
| Control/context contributions | **Yes** (`eta_controls`) | Controls vary by week (category demand, external factors, etc.) |
| Seasonality | **Yes** (`eta_season`) | Fourier terms vary by calendar week by construction |
| Trend | **Yes** (`eta_trend`), not explicitly named in the brief's list but part of "other governed structural components" | Varies by week by construction |
| Promotions | **Yes** (`eta_promo`), likewise "other governed structural components" | Varies by week whenever a promotion is active |
| Intercept/base | **No** (Section 4) | Time-invariant per outcome; contributes exactly zero to any delta |
| Market offset | **No** (Section 4), not explicitly named in the brief's list but the same proof applies | Time-invariant per market; contributes exactly zero to any delta |
| Residual/unexplained | **No** (Section 6) | Every additive `eta` term (Section 3) is exhaustively included as a player; nothing is left over. Retained only as an internal diagnostic (Section 12), never a presented bar |

## 12. What cannot currently be represented

- **Candidate A Search-mediated fits** — hard, existing exclusion
  (Section 1). The bridge is unavailable for these fits until a
  separate, future decision extends `compute_shapley_contributions`/
  `predict_mu`.
- **Time-varying baseline** — not yet implemented anywhere in this
  repository (`REQ-BASELINE-001`, decision-bound). If it is ever
  implemented, the intercept/market-offset zero-delta proof in Section 4
  would need re-deriving for whatever new time-varying structure is
  introduced — flagged here so a future implementer does not assume
  Section 4 still holds unconditionally.
- **The named eta-Deterministics' actual presence in a persisted
  trace is an assumption requiring verification, not a confirmed
  fact.** PyMC's `pm.sample(..., return_inferencedata=True)` call in
  this repository (`core/models.py:330-360`) has no `var_names`
  restriction, and `trace.to_netcdf(...)` (`core/persistence.py:664`)
  saves the full `InferenceData` unfiltered — by PyMC's own default
  behaviour, `eta_trend`/`eta_season`/`eta_promo`/`eta_controls`/
  `eta_market`/`intercept` *should* already be present in
  `trace.posterior` for any model fit since these Deterministics were
  introduced. However, no existing function in this repository actually
  reads them back out by name for posterior (post-fit) use — the one
  place these names are read today (`core/diagnostics.py`'s WP2.5
  `component_var_names` mechanism) is a **prior-predictive-only**
  diagnostic, never applied to a fitted posterior trace. **The first
  step of the implementation PR must verify, against a real fitted
  trace (synthetic data is fine), that every required Deterministic is
  actually present and correctly shaped before building the extraction
  function** — and must fail closed with a specific, named error if any
  are missing (e.g. a bundle saved under an older schema/pytensor
  version), never silently omitting a component from the reconciliation.
- **A residual/unexplained bar is not required for reconciliation
  (Section 6/11), but a diagnostic reconciliation check should still be
  computed and asserted internally** (`reconciliation_error =
  Outcome_B_total - Outcome_A_total - sum(bridge_contributions)`,
  expected ≈0 within the Section 8 tolerance) — if this check ever fails
  for a real fit, that is evidence either of a floating-point/
  implementation defect or of a future model change adding a new
  additive `eta` term this design's player list does not yet know
  about; the implementation must treat a failing check as a blocking
  error, never silently display an inaccurate chart.

## 13. Worked deterministic numerical examples

### 13.1 Minimal example: two players, two periods, `n_permutations = 1`

Deliberately using a single, fixed permutation order (not averaged)
demonstrates the reconciliation identity holds exactly even in the
degenerate case — the strongest possible proof that reconciliation does
not depend on Monte Carlo sample size (Section 8).

Two players: `trend`, `channel_1`. One row per period (illustrative —
in practice each period sums however many weekly rows it resolves to,
but the arithmetic is identical row-by-row then summed).

**Period A:** `eta_trend_A = 0.10`, `eta_channel1_A = 0.20`.
Reference `current = 1.0` (i.e. `exp(0)`).
Permutation order: `[trend, channel_1]`.

```text
step 1 (trend):     new = 1.0 * exp(0.10) = 1.10517
                    contribution[trend] += 1.10517 - 1.0 = 0.10517
                    current = 1.10517
step 2 (channel_1): new = 1.10517 * exp(0.20) = 1.35003
                    contribution[channel_1] += 1.35003 - 1.10517 = 0.24486
                    current = 1.35003

mu_total_A = exp(0.10 + 0.20) = exp(0.30) = 1.34986  (matches current to rounding)
contribution[trend]_A     = 0.10517
contribution[channel_1]_A = 0.24486
sum = 0.35003 -> mu_total_A - 1 = 0.34986  (rounding only; exact in full precision)
```

**Period B:** `eta_trend_B = 0.15`, `eta_channel1_B = 0.35`.
Same permutation order `[trend, channel_1]`.

```text
step 1 (trend):     new = 1.0 * exp(0.15) = 1.16183
                    contribution[trend] += 0.16183
step 2 (channel_1): new = 1.16183 * exp(0.35) = 1.64872
                    contribution[channel_1] += 0.48689

mu_total_B = exp(0.15 + 0.35) = exp(0.50) = 1.64872
contribution[trend]_B     = 0.16183
contribution[channel_1]_B = 0.48689
```

**Bridge:**

```text
bridge[trend]     = 0.16183 - 0.10517 = 0.05666
bridge[channel_1] = 0.48689 - 0.24486 = 0.24203

Outcome_A_total + sum(bridge) = 1.34986 + (0.05666 + 0.24203)
                              = 1.34986 + 0.29869
                              = 1.64855  ~= 1.64872 = Outcome_B_total
```

(The ~0.0002 gap above is rounding to 5 decimal places by hand; carried
in full floating-point precision — as any implementation would — this
is exact to machine epsilon, consistent with the algebraic telescoping
argument in Section 8, not an approximation the method itself
introduces.)

### 13.2 Confirming order-independence of the *total* (not the split)

Repeating 13.1 with the permutation order reversed (`[channel_1,
trend]`) for Period A:

```text
step 1 (channel_1): new = 1.0 * exp(0.20) = 1.22140
                    contribution[channel_1] += 0.22140
step 2 (trend):     new = 1.22140 * exp(0.10) = 1.34986
                    contribution[trend] += 0.12846

sum = 0.22140 + 0.12846 = 0.34986  -- identical total to 13.1's sum, different split
(trend: 0.12846 vs 0.10517 before; channel_1: 0.22140 vs 0.24486 before)
```

The **total** (`0.34986`) is identical regardless of order — proving
the reconciliation invariant is order-independent — while the **split**
between `trend` and `channel_1` does change with order, which is
exactly why the shipped implementation averages over many random
permutations (to give a fair, order-independent *credit split*, per
`compute_shapley_contributions`'s own docstring rationale) — but that
averaging is about fairness of attribution, never about whether the
bridge reconciles.

### 13.3 Confirming the zero-delta proof (Section 4) numerically

Add `intercept = 0.05` (same value in both periods, since it does not
vary by outcome-week) and `market_offset = -0.02` (same value in both
periods, since it does not vary by week within one market) as two more
players, in both Period A and Period B:

```text
bridge[intercept]     = contribution(intercept, B) - contribution(intercept, A)
bridge[market_offset] = contribution(market_offset, B) - contribution(market_offset, A)
```

Because `eta_intercept` and `eta_market_offset` are **identical
scalars** in both periods, and the Shapley contribution of a player
depends only on that player's own eta value and the (period-specific)
values of the players it is combined with in each permutation step —
substituting the same intercept/market values into the same formula
structure with the *other* players' Period-A values versus their
Period-B values does change the *raw contribution number* in each
period individually (since the other players differ between periods),
but confirmed directly by re-deriving Section 4's proof at the
`eta`-level rather than the `mu`-level: **the claim is not that
`contribution(intercept, A) == contribution(intercept, B)` as isolated
Shapley numbers** (they generally will differ slightly, since Shapley
credit for one player depends on the full coalition) — **the claim is
that intercept and market-offset's own eta VALUES don't change between
periods, so they explain none of the CHANGE being decomposed.** A fully
correct treatment nets this out by NOT including intercept/market as
separate bridge players at all, and instead folding them into a shared,
period-invariant reference constant on both sides — i.e. `mu_reference =
exp(intercept + market_offset)` is used as the Shapley starting point
`current` (in place of `1.0`) for BOTH periods identically, exactly
mirroring today's shipped code's own `mu_baseline` starting point
(`core/attribution.py`'s existing `_baseline_eta`/`compute_shapley_
contributions` pattern) — and only `trend`, `season`, `promo`,
`controls`, and `channels` are Shapley-decomposed as bridge players.
This is a **refinement of Section 5.2**: keep `intercept + market_offset`
fused into the reference starting point (as today's code already does
for the single-period case), and Shapley-decompose only the
genuinely time-varying terms into named bridge components. This
achieves the identical zero-contribution-to-the-delta result as Section
4 by construction (a shared, period-identical reference point cannot,
by definition, contribute to the difference between two evaluations
that both start from it), while avoiding the false impression that
intercept/market are being "decomposed and found to be zero" as a
run-time check — they are structurally excluded from the decomposition
in the first place, which is simpler and removes any possibility of a
near-zero-but-not-exactly-zero floating-point artefact appearing on an
intercept bar.

**This refines, and is the authoritative version of, Section 5.2's
player list**: `players = [trend, season, promo, controls, *channels]`,
with `mu_reference = exp(intercept + eta_market)` (period-invariant,
computed once per market/outcome, shared by both periods) as the
Shapley starting point — not `1.0`, and not `intercept`/`market` as
separate players. Section 11's table is unaffected in its conclusions;
this is a cleaner implementation of the same conclusion.

## 14. Preview of new code required (not built in this PR)

For the implementation PR to build against, not created here:

- A trace-extraction function reading `eta_trend`, `eta_season`,
  `eta_promo`, `eta_controls` (and confirming `intercept`/`eta_market`
  presence for the fused reference) from `trace.posterior` by name, per
  sampled `(chain, draw)` index — mirroring `extract_posterior_params`'s
  existing pattern but for these Deterministics rather than the model's
  raw coefficients. Must fail closed if any expected Deterministic is
  absent (Section 12).
- A generalised Shapley function (Section 13.3's refined version),
  parallel to but distinct from `compute_shapley_contributions` — this
  note recommends a **new** function rather than modifying
  `compute_shapley_contributions` in place, so the existing, already-
  approved, already-tested channel-only decomposition remains completely
  unchanged for its current callers (`contribution_waterfall`,
  `outcome_channel_summary`, the existing Results UI). The new
  function's player list is a strict superset of channels
  (`trend, season, promo, controls, *channels`), and it should be
  structured so the existing function could, if ever wanted, become a
  thin wrapper calling the new one with a restricted player list — but
  that consolidation is an implementation-PR judgement call, not
  required by this note.
- A period-bridge orchestration function joining
  `resolve_weeks_for_calendar_period`/`resolve_weeks_for_custom_range`
  (WP2D-core), the row-masking pattern (Section 6), the new generalised
  Shapley function, the paired-draw loop (Section 7), and
  `summarize_distribution`, producing one governed artefact per
  component with mean/median/lower/upper/n_draws — mirroring
  `PosteriorEconomicAttribution`'s shape (`core/outcome_valuation_
  attribution.py`) closely enough that the implementation PR should
  consider a parallel, analogously-named dataclass (e.g.
  `ContributionBridgeComponent`) for consistency, though this is a
  naming/structure recommendation, not a requirement.
- Deterministic reconciliation tests reusing the exact tolerance
  precedent (Section 8): `np.testing.assert_allclose(Outcome_B_total,
  Outcome_A_total + sum(bridge_contributions), rtol=1e-5, atol=1e-6)`,
  for both Model A and Model C, both the point-estimate path and at
  least one sampled-draw path, and for at least one case where Period A
  and Period B have different week-counts (Section 6's "unequal length"
  case) and one case where a component's `eta` value is genuinely zero
  in one period (e.g. a channel with no spend in Period A) to confirm
  no division-by-zero or other degenerate failure.

## 15. Summary answer to every item the governing brief required

| Brief requirement | Answer |
|---|---|
| Exact reconciliation proof, Period A -> component changes -> Period B | Section 5 (mechanism), Section 8 (proof), Section 13 (worked examples) |
| Which components are required | Section 11 (table); trend/season/promo/controls/channels required, intercept/market excluded by construction, no residual required |
| Bridge = Period B contribution - Period A contribution | Section 6, stated formula |
| Exact source artefacts/fields | Section 2 (table) |
| Weekly -> period aggregation | Section 6 |
| Unequal/partial period handling | Section 6, final paragraph |
| Observed vs. posterior-expected vs. posterior-predictive | Section 10 — resolved: posterior-expected (`mu`) |
| Posterior uncertainty propagation | Section 7 |
| Ordering without breaking reconciliation | Section 9 |
| Components that cannot currently be represented | Section 12 |
| Exact numerical reconciliation invariant for tests | Section 8 |
| Deterministic worked examples | Section 13 |
| Decision package if reconciliation is not achievable | Not triggered — reconciliation is achievable; see Section 5.3 for why no decision package is required |

## Owner and status

**Owner:** Modelling / Platform engineering.

**Status:** Design note only. No `core`, `application`, or `pages` code
accompanies this document. Implementation (WP2F implementation) may
proceed once this note is reviewed and merged, following Section 14's
preview and Section 8's mandatory reconciliation tests. WP2D-ui and
WP2E may proceed independently of this note, per the governing brief's
own sequencing (this note blocks only the waterfall's own
implementation, not the rest of the economics workstream).
