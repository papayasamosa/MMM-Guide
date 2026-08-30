# SEO partial-window handling decision record (Decision 3)

## Why this record exists

Decision 3 of the "Post-UI/UX Implementation Instructions: Approved
Business Decisions" brief requires: keep the full MMM history; use SEO
only during its valid data window; never shorten the whole MMM to SEO's
window; never turn missing SEO history into zero; mark the valid
estimation window clearly in diagnostics; if an official SEO
contribution cannot be safely estimated, fail closed for the SEO
contribution specifically, not the whole MMM. `REQ-SEO-001` explicitly
tracks this as "Decision 3, tracked separately" (its own "Out of scope"
note) and the prior Phase B session's handoff named this a genuinely
research-first item requiring review of official PyMC/PyMC-Marketing
documentation for partially-observed-predictor support before writing
any code.

This record is that research and the resulting decision. It resolves:

- which PyMC/PyMC-Marketing mechanism (if any) a partially-observed SEO
  predictor should use inside a real fit;
- the governed contract for determining and recording a variable's
  valid estimation window;
- the fail-closed eligibility gate for the SEO contribution specifically.

It explicitly does **not** implement the actual PyMC model-fitting code
(`predict.py`/`hierarchical_model.py`) — mirrors every other Phase B
step's scope boundary (declare the governed policy/contract; defer the
real fit-time wiring, which is a materially statistical change requiring
its own prior-predictive and synthetic-recovery validation, to a
separate follow-up).

## Sources consulted

Queried directly via the Context7 MCP tool against the official PyMC and
PyMC-Marketing documentation repositories (not from general
training-data recall alone):

1. **PyMC core documentation** (`/pymc-devs/pymc`, `pytensorf.py`,
   `model/core.py`, `tests/model/test_core.py`, the PyMC overview
   notebook, and `README.rst`): PyMC has a genuine, native, first-class
   missing-data mechanism — passing a NumPy array with `NaN` values (or
   an explicit `numpy.ma.MaskedArray`) as the `observed=` argument of a
   distribution automatically triggers `create_partial_observed_rv`,
   which splits the variable into an `_observed` component (fixed data)
   and an `_unobserved` component (a genuine `FreeRV`, sampled from the
   same distribution/prior as the observed part), recombined into one
   `Deterministic` usable downstream. The directly-relevant confirmed
   test (`test_missing_with_predictors`) demonstrates this exact
   mechanism used with a linear predictor term (`x * predictors`) — but
   critically, in that test the **missing values are in the outcome
   variable `y`** (the one carrying `observed=data`), not in
   `predictors` itself, which is a complete, non-missing NumPy array.
   PyMC's automatic imputation is a property of *whichever variable is
   given as `observed=` to a distribution* — it is not a general-purpose
   "fill in gaps in any input array used inside a deterministic
   expression" facility. Applying it to a *predictor* (rather than an
   outcome) would require modelling that predictor itself as its own
   random variable with an explicit likelihood/prior (e.g.
   `seo_index ~ Normal(mu_seo, sigma_seo, observed=masked_seo_array)`)
   before using the resulting joined `Deterministic` downstream as a
   regressor — a legitimate, documented technique in principle, but one
   that requires committing to a specific generative model (prior mean/
   variance, and implicitly a stationarity or smoothness assumption) for
   what SEO visibility would have looked like before Google Search
   Console tracking existed at all — a period with zero ground truth to
   validate against.
2. **PyMC-Marketing documentation** (`/pymc-labs/pymc-marketing`, the
   MMM quickstart, `mmm_example.ipynb`, `mmm_causal_identification.ipynb`,
   `mmm_roas_parametrization.ipynb`): no built-in mechanism for a
   partially-observed control/channel column is documented. The closest
   documented guidance ("Select Modeling Columns" in
   `mmm_roas_parametrization.ipynb`) is to exclude a variable that is not
   available for the full modelling window from the input dataset
   entirely for the periods it is unavailable, rather than to impute it
   — consistent with this ecosystem's general practice of only
   supplying a column real values for the periods it genuinely covers,
   not with fabricating values.

No further external web search was used; the two libraries' own
documentation directly answered the open architectural question (whether
a native, off-the-shelf imputation mechanism exists for a predictor, and
what PyMC-Marketing's own idiom does instead).

## What this record does not decide

- The actual PyMC/PyTensor code implementing the chosen gating
  mechanism inside a real Candidate-A-or-otherwise SEO causal pathway —
  a separate, materially statistical follow-up requiring its own
  prior-predictive checks and synthetic-recovery validation, exactly
  like the Google Trends anchor's fixed-loading constraint
  (`docs/google_trends_brand_demand_anchor_decision_record.md`) and
  `REQ-LATENT-001` Requirement 4's own deferred items.
- The functional form/transformation the SEO visibility index takes
  once it does enter a regression (`REQ-SEO-001`'s still-open item,
  Decision 6/Phase C scope).
- Per-channel minimum data-support numeric thresholds
  (`REQ-DATASUPPORT-001` — deliberately not invented here; this
  record's eligibility gate defers to it rather than hard-coding a
  week-count).

## Decisions required

### W1. How to represent "no SEO source data at all" versus "SEO source
data confirmed zero visibility" versus "SEO source data present"

**Decision: reuse `core.coverage`'s existing eight-state canonical
missingness vocabulary rather than invent a parallel one.**
`REQ-COVERAGE-001` already governs exactly this distinction at the
variable level (`VariableCoverageRecord`, `CoverageSegment`,
`STATE_MISSING_EXPECTED`/`STATE_UNAVAILABLE_SOURCE`/`STATE_UNKNOWN` for
"genuinely never queried," versus `core.seo_visibility`'s own
`STATE_OBSERVED_ZERO` for "queried, confirmed zero impressions," versus
`coverage_state=None` for "queried, real non-zero data"). Decision 3's
own text is explicitly framed by the prior Phase A session as "already
a direct instance of `REQ-COVERAGE-001`'s existing standing invariants"
— this record does not re-litigate that, it builds the missing
*window-determination and gating* logic on top of the vocabulary that
already exists.

### W2. Whether to natively impute the SEO predictor via PyMC's
`observed=`-masked-array mechanism (source 1 above)

**Candidate W2-A — model SEO visibility as its own random variable with
a generative prior, observed via a masked array, letting PyMC impute
pre-window values from the fitted distribution.** Rejected as the
primary mechanism: this is architecturally real and well-documented
(source 1), but it requires committing to an unvalidatable generative
assumption about SEO visibility before Google Search Console tracking
existed — there is no ground truth for those weeks, so "imputed" values
would be presented with a false air of being estimated from evidence
when they are actually pure prior extrapolation with no way to check
recovery. This is exactly the kind of unvalidated statistical
extrapolation the "fail closed... if an official SEO contribution can't
be estimated safely" language warns against, not a preferred first
choice. Noted as a possible *future* refinement, not adopted here — a
future session choosing it must run the same prior-predictive/
synthetic-recovery validation `REQ-LATENT-001` Requirement 4 already
requires for any such structural choice.

**Candidate W2-B — a windowed/gated regressor: the SEO contribution term
is only active (structurally included in the outcome predictor) during
weeks within SEO's valid data window; outside that window, the term is
architecturally switched off, never assigned or reported as "zero SEO
visibility."** This matches PyMC-Marketing's own documented idiom
(source 2: exclude a variable from the modelled periods it doesn't
cover, don't fabricate values for it) and requires no generative
assumption about periods with literally no evidence. The full MMM's
time index, all other channels/controls, and the final-outcome
likelihood are completely unaffected for every period — satisfying
"keep the full MMM history" and "never shorten the whole MMM to SEO's
window" exactly. Any internal PyTensor placeholder value needed purely
to keep a `switch`/gating tensor operation numerically well-defined at
excluded positions (a well-known PyTensor requirement — both branches of
`pytensor.tensor.switch` must evaluate to a finite number even though
only one branch's result is used) is an internal computational device
only: it is never stored as, reported as, or interpreted as "the SEO
visibility value that week" in this repository's actual governed data
records (`SeoPositionalVisibilityObservation` keeps `coverage_state`
correctly unresolved/missing for that week regardless of what internal
placeholder a future fit-time implementation uses) — satisfying "never
turn missing SEO history into zero" at the data-contract level, which is
the level this record is responsible for.

**Decision: W2-B.** Recorded as the approved architecture direction for
a future fit-time integration; not implemented as PyMC/PyTensor code by
this record (see "What this record does not decide").

### W3. How the valid window itself is determined and recorded

**Decision:** a governed `SeoValidEstimationWindow` record per market,
derived deterministically from a supplied coverage/observation series:
the window's start is the first week whose coverage state indicates SEO
data was actually queried and returned (i.e. **not** one of
`REQ-COVERAGE-001`'s "never queried" states —
`missing_expected`/`unavailable_source`/`unknown`); its end is the last
such week. A week with `observed_zero` coverage (confirmed
zero-impression week, `core.seo_visibility`'s own state) counts as
*within* the window — it is real, queried, confirmed evidence, not an
absence of data. This mirrors `VariableCoverageRecord`'s existing
`observed_start`/`observed_end` fields conceptually, but is implemented
as its own lightweight record (not by extending
`VariableCoverageRecord` itself) because this record's window
determination is SEO-observation-specific (built directly from
`SeoPositionalVisibilityObservation.coverage_state`, not from a generic
coverage matrix) and because Decision 3's brief scope is the SEO
predictor specifically, not a change to `REQ-COVERAGE-001`'s
general-purpose contract.

A window with **no** in-window weeks at all (SEO data literally never
observed) is a valid, representable state (`SeoValidEstimationWindow`
with `start_week=None`, `end_week=None`) — not an error — since a market
with no GSC coverage yet is a real, expected condition this record must
handle without crashing.

### W4. The fail-closed eligibility gate

**Decision:** `assess_seo_contribution_window_eligibility` mirrors
`core.latent_state_identification.is_eligible_for_official_use`'s
fail-closed pattern: an SEO contribution is eligible for official
reporting/planning/optimisation only when (a) a valid window exists at
all, and (b) the window's length in weeks meets an *approved* minimum
data-support threshold. No specific number is invented here — mirroring
`REQ-DATASUPPORT-001`'s own established discipline
(`SupportThresholds` fields deliberately default to `None`), this
record's gate defaults to `not_identified`-equivalent
(`"insufficient_evidence_no_approved_threshold"`) until a threshold is
separately approved, and is designed to accept an approved threshold as
an explicit parameter once one exists rather than hard-coding a guess.

## Implementation

`ancestry_mmm/core/seo_partial_window_policy.py`:

- `SeoValidEstimationWindow` — the governed per-market window record
  (W3).
- `determine_valid_estimation_window` — deterministic window
  determination from a supplied sequence of
  `SeoPositionalVisibilityObservation`-shaped `(week, coverage_state)`
  pairs (W3), reusing `core.coverage`'s vocabulary directly.
- `classify_week_relative_to_window` — classifies one week as
  `before_window` / `within_window` / `after_window` / `no_window_data`
  relative to a determined window, for diagnostics display (satisfies
  "mark the valid estimation window clearly in diagnostics").
- `SEO_GATED_REGRESSOR_ARCHITECTURE` — a governed, documented constant
  recording the approved W2-B architecture direction as structured
  metadata (never executable PyTensor code) for a future fit-time
  integration to consume.
- `SeoContributionEligibility`,
  `assess_seo_contribution_window_eligibility` — the fail-closed gate
  (W4), never exposing a bare boolean, always carrying a disclaimer.

Tests: `ancestry_mmm/tests/test_seo_partial_window_policy.py`, including
window determination from a mixed coverage-state series, the
all-missing (no window) case, the `observed_zero`-counts-as-within-
window case, week classification in all four states, and the
eligibility gate's fail-closed behaviour with and without an approved
threshold.

## Owner and status

Owner: Modelling / Platform engineering (window-determination policy
and contract); the actual fit-time gating mechanism (W2-B) requires
Modelling sign-off on its own prior-predictive validation before use,
not yet sought.

Status: implemented and tested, 2026-08-30. `REQ-SEO-001` addendum
(below) records this resolution at the requirement level.
