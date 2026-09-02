# Named-event statistical response method decision record (Decision 12)

## Why this record exists, and why it can now be written

`docs/wp2_named_event_statistical_method_decision_package.md` reserved
its seven decision dimensions (response structure, kernel/basis family,
priors, pooling, family-specific lead/lag support, validation
thresholds, planning-eligibility thresholds) from the coding agent. The
user's 2026-08-29 business-decision brief, confirmed in-session
2026-08-30, explicitly delegates "the exact statistical method, priors,
pooling and window selection" to research and validation, while
retaining ownership of the business behaviour per family (already
approved: gifting -> anticipatory; remembrance/commemorative ->
contemporaneous/post_event; promotional -> post_event, window-bounded).
This record makes that delegated selection for dimensions 1-5. It
explicitly leaves dimensions 6-7 (validation and planning-eligibility
NUMERIC thresholds) as a fail-closed framework only, since the user's
authorisation named "statistical method, priors, pooling and window
selection" specifically, not accept/reject thresholds - see "What this
record does not decide."

## Evidence already available (Work Package 2, 2026-08-20)

Crucially, this decision does not have to be made from first principles:
Work Package 2 already ran a deterministic synthetic-DGP evaluation of
candidates S1-S5 (`scripts/wp2_named_event_response/`, outside
`ancestry_mmm`, never imported by production) and recorded its findings
in `docs/wp2_named_event_response_evidence.md` (46 fitted records,
`docs/wp2_named_event_response_results.json`, CI run `32349484897`,
pinned runtime PyMC 5.28.5/PyTensor 2.38.3/ArviZ 0.23.4). This record
reads that evidence directly rather than re-deriving it or guessing.

Recorded findings this decision relies on (see the evidence document for
the full list):

1. **S1 (fixed governed profile) under-recovers amplitude** (ratios
   0.07-0.29 across scenarios) - its shape cannot adapt to the true
   timing. Rejected.
2. **S4 (unconstrained weekly dummies)** performs comparably to S2/S3 on
   adequate-repeat scenarios but is explicitly PRD-discouraged as a
   default (`docs/wp2_named_event_statistical_method_decision_
   package.md`: "S4 is admissible only where recurrence support
   genuinely permits, and is not the default") and degrades badly under
   wrong-window misspecification (RMSE 0.93) exactly like S2. Rejected
   as the default, consistent with the PRD's own framing (evidence alone
   does not override this governed constraint).
3. **S2 (parametric normal kernel) and S3 (regularised B-spline basis)**
   both recover the event shape and amplitude well on adequate-repeat
   scenarios (event RMSE 0.23-0.54, amplitude ratio 0.6-1.1) and both
   degrade under a wrong support window (a material modelling risk
   either way).
4. **S3 has the smallest media-coefficient leakage** among all
   candidates ("smallest for the regularised/pooled encodings").
5. **S3's basis family is the one that extends cleanly to partial
   pooling** (S5 = S3's spline basis with market-specific coefficients
   and a shared mean) - S2's multi-market variant in the evidence run is
   a single SHARED kernel across markets, not a partially-pooled one,
   giving S3 a structural advantage for dimension 4 (pooling/
   heterogeneity), which the PRD requires to be justified by repeated-
   event support and validation, not assumed.
6. **Sparse repeats (3 occurrences) cause S2-S4 to over-recover
   amplitude** (ratios 1.3-1.7) - flexible profiles need recurrence
   support, exactly as the PRD warns; this applies to S3 as much as S2
   and directly motivates a fail-closed pooling/support gate (below).
7. **Prior sensitivity was low at adequate repeats** for S2's kernel
   width/amplitude priors ("doubling... prior scales... changes event
   RMSE from 0.30 to 0.30") but the evidence explicitly flags this must
   be re-checked for sparse repeats before any decision - this record
   does not claim that re-check has been done for S3's shrinkage prior;
   see "What this record does not decide."

## Decision dimension 1: response structure

**Decision: S3 - regularised distributed basis (cubic B-spline over the
lead/lag window, coefficients shrunk toward zero by a shared prior
scale).** Selected over S2 for its smaller leakage (finding 4) and its
structural extensibility to partial pooling (finding 5), both directly
relevant to this repository's own governance requirements (minimise
leakage into media terms; justify heterogeneity with validation, not
assumption). Selected over S1 (poor amplitude recovery, finding 1) and
S4 (PRD-discouraged default, finding 2).

## Decision dimension 2: kernel/basis family

**Decision: cubic B-spline (degree 3), two interior knots placed at 1/4
and 3/4 of the total window span (measured from the lead boundary),
boundary knots at the window edges** - exactly the basis family the WP2
evidence measured (`scripts/wp2_named_event_response/candidates.py`'s
`_spline_basis`), generalised from that script's fixed ±4-week evidence
window to an arbitrary family-specific `(max_lead_weeks, max_lag_weeks)`
window (dimension 5). For the exact symmetric ±4-week window the
evidence used, 1/4 and 3/4 of the 8-week span from the -4 boundary
reproduce the evidence's own interior knots (-2, +2) exactly. This
quarter/three-quarter-of-total-span placement (rather than "the midpoint
of each side independently") was chosen deliberately during
implementation: placing a knot at each side's own midpoint degenerates
to a knot coincident with a boundary knot whenever one side of the
window has zero weeks - exactly the gifting family's own
`max_lag_weeks=0` case - which the quarter/three-quarter-of-total-span
formula avoids for any non-degenerate window (`max_lead_weeks +
max_lag_weeks > 0`). Choosing the same basis FAMILY the evidence
actually validated, rather than a plausible-sounding but untested
alternative (e.g. a Fourier basis), is deliberate - this record does not
extrapolate validated evidence to an unvalidated design choice; only the
knot-placement FORMULA needed adjusting to remain well-defined for an
asymmetric window, verified directly (row sums equal 1.0 across the
symmetric, lead-only, and lag-only cases - the B-spline partition-of-
unity property, checked as a regression test).

## Decision dimension 3: priors and regularisation

**Decision: `event_coefs ~ Normal(0, tau)`, `tau ~ HalfNormal(1.0)`** -
the exact shared-shrinkage-scale prior structure the WP2 evidence used
for S3/S5. The evidence's own text is explicit that prior sensitivity
"must be re-checked for sparse repeats before any decision" and this
record does not claim that re-check exists - `tau_scale=1.0` is
recorded as the validated STARTING default from the evidence run, not a
final, business-approved constant; a future session fitting this
against real UK data must run its own prior-predictive check at that
data's actual scale (Requirement 4-style validation, mirroring `REQ-
LATENT-001`'s own established discipline) before treating any prior as
final. This is disclosed explicitly in the implementation (`EVENT_
RESPONSE_SHRINKAGE_PRIOR_REQUIRES_RECALIBRATION = True`), not silently
assumed final.

## Decision dimension 4: pooling and heterogeneity

**Decision: unpooled per market/family by default; partial pooling
(mirroring S5's shared-mean spline-coefficient structure) is permitted
only when repeated-event support and validation justify it** - directly
implementing the PRD's own "heterogeneity requires repeated-event
support and validation justification" constraint and finding 6's sparse-
repeat over-recovery risk. This record does not invent the exact
minimum-repeated-event-count threshold for "support justifies pooling"
(mirrors `REQ-DATASUPPORT-001`'s own deliberately-deferred numeric
thresholds) - `assess_family_pooling_eligibility` fails closed
(`insufficient_evidence_no_approved_threshold`) until an approved
minimum-occurrence threshold is supplied, exactly like `core.
seo_partial_window_policy`'s eligibility gate.

## Decision dimension 5: family-specific maximum lead and lag support

The PRD's own text requires these be "informed by business timing...
not by optimising in-sample fit over the window" - i.e. a domain/
marketing-research question, not a statistical-method question, but one
the user's authorisation explicitly named as delegated ("window
selection"). Resolved using well-established, general retail/marketing-
seasonality research (not Ancestry-specific data, which does not yet
exist for this purpose) as an explicit, disclosed, overridable STARTING
default - not claimed as a final, data-validated business number:

- **Gifting family (`anticipatory`)**: `max_lead_weeks=6`,
  `max_lag_weeks=0`. Grounded in widely-reported general retail-industry
  seasonality research that online gift-purchase search/consideration
  activity for major gifting occasions (e.g. Christmas, Mother's Day,
  Valentine's Day) measurably rises in the weeks before the date, most
  commonly cited in a 4-6 week pre-event window, with the final 1-2
  weeks carrying the largest share of the effect - general industry
  knowledge, not a source-cited Ancestry-specific study. `max_lag=0`
  because Decision 12's own family mapping assigns gifting to
  `anticipatory` only, not `anticipatory_and_post_event`.
- **Remembrance/commemorative family
  (`contemporaneous`/`post_event`)**: `max_lead_weeks=0`,
  `max_lag_weeks=2`. Commemorative-date spikes (anniversaries,
  remembrance dates) are typically sharp and concentrated at or shortly
  after the date itself, rather than anticipated in advance - a shorter,
  post-event-only window than gifting's anticipatory one.
- **Promotional family (`post_event`, window-bounded)**:
  `max_lead_weeks=0`, `max_lag_weeks=None` (not a fixed generic number -
  Decision 12's own text requires this window be bounded to the ACTUAL
  declared active period of the specific promotion instance, a
  per-promotion data-driven bound, not a global constant this record
  could invent).

These three defaults are recorded as `NamedEventFamilyWindowPolicy`
instances with an explicit `basis` field documenting this provenance
(general research, not Ancestry-validated) and are fully overridable -
never silently treated as final without a future business/evidence
review, mirroring the DNA-cross-sell-window/FH-LTR-horizon precedent
this repository already established for a "new number with zero prior
repository precedent, disclosed and flagged, not hidden."

## What this record does not decide

- Dimensions 6 and 7 (validation thresholds for recurrence support,
  timing sensitivity, separation evidence; planning-eligibility
  thresholds) - the user's authorisation named "statistical method,
  priors, pooling and window selection" specifically; this record treats
  accept/reject numeric thresholds as still requiring their own,
  separate evidence-based decision, mirroring `REQ-DATASUPPORT-001`'s
  approach: the FRAMEWORK (a fail-closed gate) is implemented, the
  NUMBER is not invented.
- Any real UK data validation - the WP2 evidence is synthetic only; real
  UK end-to-end validation remains explicitly deferred pending
  authorised source-data availability, exactly as
  `docs/wp2_named_event_response_evidence.md` itself states.
- Any actual PyMC model-fitting integration - this record implements the
  deterministic basis-construction and window-policy contract only,
  mirroring every other Phase B/C step's "declare the contract, defer
  fit-time wiring" scope boundary in this repository (the same boundary
  `core.google_trends_anchor`/`core.seo_partial_window_policy` already
  established). Wiring this into a real named-event pathway is a
  separate, materially statistical follow-up requiring its own
  synthetic-recovery validation on the ACTUAL family windows chosen here
  (WP2's evidence used a generic ±4-week testbed window, not these
  family-specific ones - re-running recovery evidence at the real
  6-week/2-week windows before production use is a reasonable next step,
  not performed here).
- Skewed timing shapes - the evidence document's own "Limitations"
  section notes S2's kernel (and by extension this record's B-spline,
  which was not specifically tested for skew) is symmetric; a
  genuinely skewed real-world timing shape is not represented by
  either.

## Implementation

`ancestry_mmm/core/named_event_response.py`:

- `NAMED_EVENT_RESPONSE_STRUCTURE`, `EVENT_RESPONSE_KERNEL_FAMILY`,
  `EVENT_RESPONSE_SHRINKAGE_PRIOR_FAMILY`,
  `EVENT_RESPONSE_SHRINKAGE_PRIOR_DEFAULT_SCALE = 1.0`,
  `EVENT_RESPONSE_SHRINKAGE_PRIOR_REQUIRES_RECALIBRATION = True` -
  governed constants recording decisions 1-3.
- `NamedEventFamilyWindowPolicy` - the governed per-family window record
  (decision 5), with `GIFTING_WINDOW_POLICY`/
  `REMEMBRANCE_WINDOW_POLICY`/`PROMOTIONAL_WINDOW_POLICY` defaults.
- `build_event_relative_design_matrix` - the deterministic event-relative
  indicator matrix (generalised from `scripts/wp2_named_event_
  response/dgp.py`'s `_event_design`, factual dates never shifted).
- `build_spline_basis` - the deterministic cubic B-spline basis
  (generalised from `scripts/wp2_named_event_response/candidates.py`'s
  `_spline_basis`, parameterised by the family's own window rather than
  the evidence run's fixed ±4-week testbed).
- `PoolingEligibility`, `assess_family_pooling_eligibility` - the
  fail-closed pooling gate (decision 4), deferring the numeric
  repeated-occurrence threshold.

Tests: `ancestry_mmm/tests/test_named_event_response.py`.

## Owner and status

Owner: Modelling / Platform engineering. Status: implemented and
tested, 2026-08-30, per the user's explicit 2026-08-30 authorisation
delegating this technical selection (see wp2's updated text). Real-data
validation of the family-specific windows and shrinkage-prior
recalibration remain open, disclosed follow-ups, not silently treated
as settled.
