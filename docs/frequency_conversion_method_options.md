# Frequency-conversion method decision options

Status: decision-support analysis for REQ-COVERAGE-001 S4 (`docs/approved_requirements/REQ-COVERAGE-001.md`)
and the `core.frequency_alignment` contracts it authorises (Work Package C, PR #162). This
document does not itself approve a conversion method. It does not build, register, or wire
any method into `core.frequency_alignment`'s conversion-method registry, `data.pipeline`, or
any Streamlit page. It is the evidence base a human reviewer uses to approve one candidate
per variable class (or reject all of them and request a different one) via a future,
separately-scoped decision record.

Reviewed at `main` commit `2f656bc228df9299ea4d54566594819e41c9a672` (PRs #160, #161, #162
merged; no open pull requests at review time).

No conversion method is approved, registered, or implemented by this document.

---

## 1. Why this document exists

REQ-COVERAGE-001 S4 authorises variable-class-specific frequency-conversion semantics but
explicitly does not approve a concrete method for any class ("Out of scope": "any specific
imputation formula, interpolation kernel, or default fill method not named in S4").
`core.frequency_alignment` (Work Package C) built the *architecture* a conversion method
plugs into — `ConversionMethodSpec`, a registry that starts empty, `AlignmentSpecification`,
and the leakage/definition-break/support-boundary checks — but its `_METHOD_REGISTRY` has
zero entries, so `evaluate_alignment_request` reports `unsupported_no_approved_method` for
every real request today.

This document surveys candidate methods per variable class so a human reviewer has a
structured basis for approval, without this repository (or a coding agent) inventing that
statistical decision unilaterally. For each candidate the nine dimensions below are assessed.

## 2. Assessment dimensions

Every candidate below is assessed against the same nine questions:

1. **Constancy assumption** — what quantity does this method assume is constant, or how does
   it assume the source-period total/level is distributed, within the source period?
2. **Reconciliation** — does the disaggregated series, re-aggregated back to the source
   period, reproduce the original source-period total/level exactly?
3. **Publication-lag behaviour** — does the method require information that would not
   actually have been published at the reconstructed sub-period's own time (leakage risk)?
4. **Revision-vintage behaviour** — how does the method behave when a source value is later
   revised (does the disaggregated history change retroactively, and is that itself a problem
   for a frozen backtest)?
5. **Boundary behaviour** — what happens at the first/last known observation, and at a
   declared source-definition break?
6. **Uncertainty implication** — does the method have a natural, defensible uncertainty
   representation for the sub-period values it produces, or does it silently present a
   point estimate as if it were as reliable as an actually-observed sub-period value?
7. **Backtest reconstruction implication** — can an expanding-window backtest reconstruct
   "what this method would have produced using only data available at that historical point,"
   or does the method require full-sample information that a backtest cannot honestly supply?
8. **Risk of artificial sub-period variation** — does the method invent week-to-week (or
   otherwise sub-period) variation that does not reflect any genuine signal in the source
   data, risking the model fitting noise the method itself manufactured?
9. **Risk of attenuation/overconfidence** — does the method risk flattening genuine
   variation (attenuation), or presenting a smoothed/interpolated series with the same
   apparent precision as directly observed data (overconfidence)?

## 3. Variable classes

`core.coverage.VARIABLE_CLASSES` / `core.frequency_alignment.ConversionMethodSpec.variable_class`
currently defines five classes. Each is addressed separately below — REQ-COVERAGE-001 S4 is
explicit that "a single default method must never be applied across classes."

---

## 4. `flow_count`

A quantity accumulated *over* the source period (e.g. monthly spend, monthly conversions,
monthly impressions) — the source-period value is a sum, not a snapshot.

| # | Dimension | A. Equal temporal allocation | B. Indicator-based disaggregation (Denton/Chow-Lin style) | C. Step repetition (repeat monthly total each sub-period) | D. No conversion (fit at native frequency only) |
|---|---|---|---|---|---|
| 1 | Constancy assumption | The flow is uniformly distributed across every sub-period in the source period (e.g. spend is flat within the month) | The flow follows the *shape* of a chosen higher-frequency indicator series (e.g. impressions, web traffic, a related already-weekly channel), scaled so the source-period sum matches | The full source-period total is assigned to every sub-period, not divided | No sub-period value is manufactured; the model consumes this variable only at its own native cadence |
| 2 | Reconciliation | Exact by construction (sub-periods sum to the source total) | Exact by construction if the benchmarking constraint is enforced (Chow-Lin/Denton explicitly solve for this); approximate otherwise | Not reconciled — summing the repeated value across sub-periods over-counts the source total by a factor equal to the sub-period count | N/A — no disaggregated series to reconcile |
| 3 | Publication-lag behaviour | Safe — needs only the already-published source-period total | Needs the indicator series' own values at the same sub-periods; if the indicator itself has a shorter publication lag than the flow variable, no leakage; if the indicator is itself lagged or revised, must be checked independently | Safe — needs only the source-period total, but overstates value in every sub-period until the *next* source observation is known, which is itself a leakage risk for periods within the current, still-unclosed source window | Safe — no interpolation to leak from |
| 4 | Revision-vintage behaviour | A later revision to the source total changes every sub-period allocation proportionally; a frozen backtest vintage must be explicit about which source revision it used | Sensitive to both the source revision and the indicator series' own revisions — compounds two revision risks | A later revision to the source total changes every previously-assigned sub-period value retroactively | Not applicable at native frequency, but the *modelling* frequency itself is then constrained to the source's own cadence |
| 5 | Boundary behaviour | Well-defined for any complete source period; an incomplete final period (partial month) requires an explicit partial-period convention | Requires the indicator series to exist and be non-degenerate (non-zero, non-constant) across the full source period; degenerates to method A's assumption if the indicator is flat | Requires knowing the *next* source period's start to know when to stop repeating; the most recent, still-open source period has no defined stopping point without an explicit "current incomplete period" rule | Boundary is whatever the source's own coverage boundary already is (`core.coverage` handles this today) |
| 6 | Uncertainty implication | No natural uncertainty band; sub-period values are asserted with the same apparent confidence as an average, though the true within-period distribution is unknown | Uncertainty could in principle be derived from how well the indicator historically predicted known higher-frequency ground truth (where such ground truth exists to validate against), but no such validation exists in this repository today | No natural uncertainty band; systematically wrong for any period boundary that does not align with the source period | None — the variable's own real observed uncertainty (there is none within a native period; it is what it is) is preserved by not being altered |
| 7 | Backtest reconstruction implication | Reconstructable at any historical point using only that point's own source data — a genuinely leakage-safe expanding-window step | Reconstructable only if the indicator series is itself fully available at that historical point; if the indicator is chosen or fitted using full-sample information, the backtest is compromised | Reconstructable, but see finding 3 (systematically wrong until the period closes) | Reconstructable trivially, but the *model* itself is then constrained to fit and backtest only at the native cadence for this variable |
| 8 | Risk of artificial sub-period variation | None — by construction every sub-period is identical, so it cannot manufacture spurious within-period variation | Manufactures sub-period variation that mirrors the indicator's own shape — genuine risk if the indicator's shape does not actually reflect this specific flow variable's true within-period distribution | None — flat repetition, but at the wrong (over-counted) magnitude | None — no sub-period series is created at all |
| 9 | Risk of attenuation/overconfidence | Attenuates any genuine within-period variation to zero; a channel with real intra-month timing effects (e.g. concentrated end-of-month spend) is misrepresented as smooth | Depends entirely on indicator quality; a good indicator reduces both attenuation and overconfidence risk, a poor one can *introduce* spurious sharp variation the model then treats as signal | Both — flat within a period (attenuated) and wrong in total magnitude (a distinct problem from attenuation) | No attenuation risk (nothing is smoothed), but forces the model's whole predictor set to the coarsest native cadence present, which can attenuate the *model's* sensitivity to genuinely higher-frequency co-variates |

---

## 5. `stock_level`

A quantity measured *at a point in time* (e.g. active subscriber count, cumulative account
base) — the source-period value is a level, not a sum.

| # | Dimension | A. Linear interpolation | B. Step / last-observation-carried-forward (LOCF) | C. Cubic spline interpolation | D. No conversion (fit at native frequency only) |
|---|---|---|---|---|---|
| 1 | Constancy assumption | The level changes at a constant rate between two known observations | The level is constant from one observation until the next observation supersedes it | The level follows a smooth curve (continuous first/second derivative) fitted through surrounding known observations | No sub-period value is manufactured |
| 2 | Reconciliation | Exact at the known observation points by construction; sub-period values are not independently verifiable | Exact at the known observation points; every sub-period before the next observation is asserted at the prior known level | Exact at the known observation points; the curve shape between them is unverifiable without ground truth | N/A |
| 3 | Publication-lag behaviour | Requires the *next* known observation to interpolate a sub-period before it — a genuine leakage risk if used for a historical reconstruction "as of" a date before that next observation was published | Safe — only ever uses the most recent already-published observation | Requires surrounding (often several) known observations, typically including future ones relative to the interpolated sub-period — the most leakage-prone of the four | Safe |
| 4 | Revision-vintage behaviour | A later-revised observation changes the interpolated path retroactively between it and its neighbours | A later-revised observation changes only the sub-periods from its own date forward (until superseded), not retroactively | A later-revised observation can change the fitted curve shape across a wider surrounding window than immediate neighbours | Not applicable at native frequency |
| 5 | Boundary behaviour | Undefined before the first observation or after the last (extrapolation, not interpolation, would be required) | Well-defined after the first observation (repeats it); undefined before the first observation | Poorly behaved at the boundaries of the observed series (spline endpoints commonly over/undershoot without an explicit boundary-condition choice) | Boundary is the source's own coverage boundary |
| 6 | Uncertainty implication | No natural uncertainty band; presents a straight-line guess as if it were observed | No natural uncertainty band, but the *assumption* (level hasn't changed) is at least an explicit, auditable one rather than a manufactured trajectory | No natural uncertainty band; the smoothness itself can create false confidence that the true path was smooth | None — real native-frequency observations retain their real (typically minimal) uncertainty |
| 7 | Backtest reconstruction implication | Only reconstructable at a historical point if using only *past* observations (i.e. extrapolation, not interpolation, changing the method's own behaviour depending on whether it's used for backtest-reconstruction versus final-history construction) | Reconstructable at any historical point using only past-known observations — genuinely leakage-safe for a backtest | Not reconstructable for a genuine backtest without either look-ahead or switching to a different (extrapolating) method near the reconstruction boundary | Reconstructable trivially at native cadence |
| 8 | Risk of artificial sub-period variation | Low — produces a smooth, monotonic-between-points path, not spurious noise | None — flat between observations | Can produce non-monotonic wiggles between observations that do not reflect any genuine signal, particularly with sparse or unevenly-spaced source observations | None |
| 9 | Risk of attenuation/overconfidence | Moderate overconfidence risk (a straight line looks like real data) | Understates genuine change that occurred between observations (attenuation of the *rate* of change specifically), but does not fabricate a plausible-looking trend | High overconfidence risk — a smooth curve is the most visually persuasive of the four despite having no more genuine information behind it than the same known observations | No overconfidence risk, but analytically limited to native cadence |

---

## 6. `rate_index`

A ratio, percentage, or index value (e.g. CPI, a market-share rate, a cost-per-unit index) —
not meaningfully summed across periods; typically reported as a snapshot or period-average
rate.

| # | Dimension | A. Step / LOCF | B. Linear interpolation | C. No conversion (fit at native frequency only) |
|---|---|---|---|---|
| 1 | Constancy assumption | The rate is constant from one observation until the next supersedes it | The rate changes at a constant pace between two known observations | No sub-period value is manufactured |
| 2 | Reconciliation | N/A (a rate is not additive across periods, so there is no source-period total to reconcile against) | N/A, same reason | N/A |
| 3 | Publication-lag behaviour | Safe | Requires the next known observation — leakage risk before that point is published | Safe |
| 4 | Revision-vintage behaviour | Changes only from the revised observation's own date forward | Changes the interpolated path between the revised observation and its neighbours retroactively | Not applicable at native frequency |
| 5 | Boundary behaviour | Well-defined after the first observation; undefined before it | Undefined outside the observed range | Boundary is the source's own coverage boundary |
| 6 | Uncertainty implication | No natural band, but an explicit, auditable "hasn't changed" assumption | No natural band; a straight-line guess presented as data | None |
| 7 | Backtest reconstruction implication | Reconstructable at any historical point using only past observations | Not reconstructable for a genuine backtest without look-ahead | Reconstructable trivially at native cadence |
| 8 | Risk of artificial sub-period variation | None | Low-to-moderate, same reasoning as `stock_level` | None |
| 9 | Risk of attenuation/overconfidence | Understates the *rate of change* between observations (a rate genuinely may move gradually, and a step function misses that), but never fabricates a plausible-looking trend | Overconfidence risk (a smooth-looking rate implies more precision than the sparse underlying observations support) | No overconfidence risk, but limited to native cadence |

---

## 7. `survey_measurement`

A periodically-fielded measurement (e.g. a brand-tracker survey, a panel-based awareness
metric) — typically irregular cadence, subject to sampling noise and methodology revisions,
and often has a meaningfully long publication lag from fielding to release.

| # | Dimension | A. Step / LOCF | B. Linear interpolation | C. Native-cadence-only covariate (no sub-period disaggregation) |
|---|---|---|---|---|
| 1 | Constancy assumption | The measured construct is constant from one fielding until the next | The measured construct changes at a constant pace between two fieldings | No sub-period value is manufactured; the survey enters the model only at its own fielding cadence |
| 2 | Reconciliation | N/A (a survey reading is not additive) | N/A | N/A |
| 3 | Publication-lag behaviour | Safe once the observation is genuinely published, but survey publication lag is often materially longer than other variable classes' and must be tracked explicitly per REQ-COVERAGE-001 S4's "publication/release timing" requirement | Requires the next fielding — compounds an already-longer publication lag with the interpolation's own look-ahead requirement, the highest-risk combination in this document | Safe |
| 4 | Revision-vintage behaviour | Survey methodology changes (question wording, panel composition, weighting) are a common real-world source of REQ-COVERAGE-001's "source-definition break" — must be checked via `check_definition_break_crossing`, not assumed absent | Same methodology-break risk as Step, plus the interpolation itself changes retroactively on a later fielding | Not applicable at native (fielding) frequency |
| 5 | Boundary behaviour | Well-defined after the first fielding; undefined before it | Undefined outside the observed range, and survey fieldings are frequently irregularly spaced, making "outside the range" a common practical case | Boundary is the source's own coverage boundary |
| 6 | Uncertainty implication | Sampling error/margin, when reported by the survey vendor, is a genuine, usable uncertainty signal this method can carry forward unchanged between fieldings — the strongest natural uncertainty story of the three | No natural band; compounds survey sampling noise with interpolation guesswork | Preserves the survey's own real uncertainty (sampling margin) without alteration |
| 7 | Backtest reconstruction implication | Reconstructable at any historical point using only past fieldings | Not reconstructable for a genuine backtest without look-ahead, and irregular fielding cadence makes "the next observation" an unpredictable distance away | Reconstructable trivially at native (fielding) cadence |
| 8 | Risk of artificial sub-period variation | None | Moderate — irregular fielding spacing can produce large, arbitrary-looking jumps in the interpolated slope between differently-spaced fielding pairs | None |
| 9 | Risk of attenuation/overconfidence | Understates genuine gradual change between fieldings, but is transparent about doing so | Highest overconfidence risk of the three — presents a smooth trend through what may be noisy, infrequent, and methodologically-inconsistent survey readings | No overconfidence risk, but likely the most restrictive on modelling cadence given typically-sparse survey fielding |

---

## 8. `event_flag`

A binary or categorical indicator (e.g. a promotion window, a product launch, a
methodology-change marker) — generally already defined at whatever grain the event's own
real-world start/end dates specify, not a statistically-converted quantity in the same sense
as the other four classes.

| # | Dimension | A. Full-period overlap (flag every sub-period the source period overlaps) | B. Exact-date sub-period only (flag only the sub-period containing the event's precise date, where known) | C. No conversion needed (event already defined at target grain) |
|---|---|---|---|---|
| 1 | Constancy assumption | The event's effect/relevance is assumed to apply uniformly across every sub-period the source period touches, even partially | The event is assumed to be a point-in-time occurrence whose relevance is concentrated at its exact sub-period, not smeared across the whole containing source period | No assumption is made; the source data already specifies start/end at (or finer than) the modelling grain |
| 2 | Reconciliation | N/A (a flag is not additive) | N/A | N/A |
| 3 | Publication-lag behaviour | Safe if the source period's own boundaries were already known and published in advance (e.g. a planned promotion window) | Same, but requires knowing the exact date, which for some events (e.g. an unplanned competitor action) may itself only become known after the fact | Safe |
| 4 | Revision-vintage behaviour | A later change to the source period's boundaries changes which sub-periods are flagged retroactively | A later correction to the exact date changes exactly one sub-period's flag | Not applicable — no conversion performed |
| 5 | Boundary behaviour | A source period that only partially overlaps a sub-period at its start/end still flags that whole sub-period — can overstate the event's temporal footprint at the boundary sub-periods specifically | Understates the event's footprint if its real-world effect genuinely does extend across the whole source period (e.g. a "March promotion" whose effect isn't limited to a single day) | Boundary behaviour is whatever the source data's own convention already specifies |
| 6 | Uncertainty implication | No uncertainty concept applies to a binary flag; the risk is entirely in the boundary-overlap judgement call above, not in an unknown magnitude | Same | Same |
| 7 | Backtest reconstruction implication | Reconstructable exactly as long as the source period's own boundaries were genuinely knowable at the historical point in question | Reconstructable exactly as long as the exact date was genuinely knowable at that point | Reconstructable trivially |
| 8 | Risk of artificial sub-period variation | None (binary, not a manufactured continuous value) | None | None |
| 9 | Risk of attenuation/overconfidence | Risk of overstating the event's temporal extent (opposite failure mode from attenuation — an "inflation" risk specific to this class) | Risk of understating the event's temporal extent if its true effect is genuinely diffuse across the source period | Neither risk — but only if the source data's own grain genuinely matches the assumption being relied on downstream |

---

## 9. Cross-cutting notes (apply to every class above)

- **Definition breaks.** Every candidate above that performs any interpolation or step-repetition
  must still respect `core.frequency_alignment.check_definition_break_crossing` — a break
  blocks the *conversion*, not merely the raw join, regardless of which method is eventually
  approved.
- **Publication leakage.** Every candidate that looks at "the next observation" (linear/spline
  interpolation, and Chow-Lin/Denton-style disaggregation using a future-dated portion of the
  indicator) is leakage-prone for any *live, forward-looking* use (as opposed to constructing a
  final historical series after the fact) and must be paired with
  `core.frequency_alignment.check_publication_leakage` before being used in a backtest or a
  scenario that must not see the future.
- **No candidate above is free of every risk.** This is expected and, per REQ-COVERAGE-001 S4,
  is exactly why the method is a governed, versioned, approved decision per variable class
  rather than a silent default — the approving reviewer is choosing which risks are acceptable
  for a specific variable's actual use in the model, not selecting a universally "correct"
  method that does not exist.
- **A "no conversion" option is listed for every class deliberately.** REQ-COVERAGE-001 S1's
  standing invariants ("never truncate to the narrowest common window", "never reduce all
  markets to the smallest common variable set") permit a variable to remain at its own native
  frequency, contributing to the model only where a leakage-safe, class-appropriate mechanism
  exists — not every variable must be forced onto a single shared modelling cadence.

## 10. What this document does not do

- It does not select a method for any class.
- It does not add a `ConversionMethodSpec` to `core.frequency_alignment`'s registry.
- It does not change `core.coverage`, `data.pipeline`, or any Streamlit page.
- It does not invent a validation threshold, a specific interpolation kernel's parameters, or
  a specific benchmarking indicator series for the `flow_count` Chow-Lin/Denton candidate —
  those remain unresolved even if that candidate is later approved in principle.

## 11. Next step

A human reviewer (Data Science / Platform engineering, matching REQ-COVERAGE-001's own
ownership) selects zero or more candidates above per variable class, or requests a different
candidate not listed here. That selection becomes a new, separately-scoped approved
requirement record (e.g. `REQ-FREQ-001`) which:

- names the approved method(s) per variable class,
- registers a corresponding `ConversionMethodSpec` in `core.frequency_alignment` with
  `approved=True`,
- defines the migration/wiring plan into `data.pipeline`/Transform Pipeline (a separate,
  bounded implementation package, per REQ-COVERAGE-001 S4's precedent of not wiring an
  always-unsupported service into the live UI prematurely).

Until that record exists, `core.frequency_alignment.evaluate_alignment_request` continues to
correctly return `unsupported_no_approved_method` for every real request, and no coding agent
should register a method in the live registry based on this document alone.
