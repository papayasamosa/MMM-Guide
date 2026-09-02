# Capacity and cap semantics decision record (Decisions 10 and 18)

## Why this record exists, and why it can now be written

`docs/wp11_capacity_cap_semantics_decision_package.md` (Work Package 11)
originally reserved its S1-S3 (cap-hit status vocabulary) and G1-G3
(module-sharing timing) candidates from the coding agent, pending a
human Modelling/Platform-engineering decision. The user's 2026-08-29
"Post-UI/UX Implementation Instructions" business-decision brief (a
later, approved human instruction) explicitly delegates the *technical
selection* among those candidates to research-and-validation, while
retaining ownership of the *business* question (that capacity
constraints must exist, be flexible, and be shared across Scenario
Planner/Optimiser/Search) — already answered by Decision 10 ("Paid
Search must not claim more demand than it can realistically capture")
and Decision 18 ("real-world capacity constraints... flexible,
user-editable, shared consistently"). See wp11's own updated text
(below) for the exact delegation citation. This record is that
technical selection.

It resolves: the cap-hit status vocabulary (S1/S2/S3), the
module-sharing timing (G1/G2/G3), what "a governed source and a
versioned cap-hit rule" requires, and whether Candidate A's
reconciliation identity generalises.

It explicitly does **not**:

- invent, or claim resolved, any capacity measure/business input this
  repository's current data does not actually support (per the user's
  own carve-out: "only ask me if you discover that a required business
  input is genuinely missing, such as a capacity measure that cannot be
  derived from existing data" — no such gap was found; Candidate A's
  existing cap object and posterior binding-probability machinery
  already supply everything this record's design needs);
- change `core.search_capacity`'s existing, already-validated
  `CandidateAForwardState`/`CandidateAPosteriorOutputs` boolean
  `cap_binding` field or its reconciliation arithmetic — this record
  ADDS a new, shared classification capability that Candidate A adopts
  alongside its existing fields, never removing or silently
  reinterpreting a field already covered by passing tests;
- extend `core.graph_model_compiler`'s `capacity_constrained`
  structural validation to a second concrete pathway — no second
  capacity-constrained pathway exists yet to validate the compiler
  logic against (this is a narrower, still-legitimate application of
  "avoid guessing an unspecified future structure," not a re-reservation
  of the vocabulary/module questions this record does resolve).

## Sources consulted

1. **PyMC official documentation** (`/pymc-devs/pymc`, `censored.rst`):
   confirms `pm.Censored` as PyMC's own first-class distribution for an
   upper (or lower) bounded observation process — directly supporting
   `REQ-SEARCH-002`'s own upstream-reference citation of
   `pymc/distributions/censored.py` for Candidate A's
   `realised_paid_search_delivery = min(unconstrained_opportunity, cap)`
   structure. This confirms the existing reconciliation identity's
   algebraic form (a hard min/censoring relationship) is not a bespoke
   invention but a recognised statistical pattern, informing decision R4
   below.
2. This repository's own existing, already-approved precedent for
   "disclose the full distributional evidence, never collapse it into an
   unexplained single verdict" (`core.calibration_comparison`'s explicit
   no-verdict-field requirement, `REQ-CALIB-001`; `core.structural_
   stability.ParameterFoldComparison.point_range`'s "report movement,
   never a verdict") — directly informing decision S below, since
   `core.search_capacity.CandidateAPosteriorOutputs.probability_cap_
   binding` already exists as exactly this kind of distributional
   evidence.
3. `AGENTS.md`'s "Capacity and cap invariants" section (this
   repository's own standing invariant, the origin of the four-value
   "capped / uncapped / ambiguous / unavailable" vocabulary
   `REQ-CAP-001` already cites) — read in full before designing the
   vocabulary below, since the four values themselves are already a
   governed fact this record must satisfy, not redesign.

## Decision S: cap-hit status vocabulary

**Candidate S1 — extend the boolean to a four-value enum,
threshold-based on posterior binding probability.**

**Candidate S2 — distributional cap-hit status, no single mandatory
categorical label; the full binding-probability distribution is the
primary artefact.**

**Candidate S3 — no shared vocabulary; each pathway defines its own.**

**Decision: S1, implemented with S2's evidence-transparency
discipline never discarded.** `AGENTS.md`'s four-value vocabulary
("capped / uncapped / ambiguous / unavailable") is an already-governed,
mandatory invariant this record must satisfy, not an open design
choice — S3 is therefore rejected outright (it would leave that
invariant pathway-specific, which `AGENTS.md`'s own text does not
support: it states the invariant once, for any capacity-constrained
pathway). Between S1 and S2, the correct resolution is not
either/or: the four-value categorical label is REQUIRED (satisfying
`AGENTS.md`), but it is always computed transparently from, and
reported alongside, the full underlying distributional evidence
(`probability_binding`) that already exists in Candidate A
(`CandidateAPosteriorOutputs.probability_cap_binding`) — mirroring
source 2's "disclose evidence, never a lossy compression that hides the
underlying number" precedent. The categorical label is a derived
summary of the retained evidence, never a replacement for it.

**Concrete operational definitions** (the "what a coding agent may not
guess" items S1 needed):

- **`unavailable`**: no governed cap value exists for the
  market/period at all — `cap_value is None`, distinct from a supplied,
  finite cap of `0.0` (a genuine, if extreme, capacity limit) or an
  infinite/unbounded cap (represented explicitly, never as `None`).
- **`capped`**: a governed cap value exists, and the evidence indicates
  binding — for a single point evaluation (no posterior distribution
  supplied, e.g. observed history), this is `np.isclose(realised,
  cap)`, matching Candidate A's own existing point-evaluation
  convention exactly (`core.search_capacity.candidate_a_forward`'s
  `rtol=1e-8, atol=1e-8`, reused verbatim, not re-derived); for
  posterior-draw evidence, `probability_binding >= 1.0 - ambiguity_band`.
- **`uncapped`**: symmetric to `capped` — a point evaluation with no
  binding, or `probability_binding <= ambiguity_band` for posterior
  evidence.
- **`ambiguous`**: ONLY possible under posterior-draw evidence (a point
  evaluation is definitionally either binding or not — there is no
  "ambiguous" state without a distribution to be uncertain over):
  `ambiguity_band < probability_binding < 1.0 - ambiguity_band`.

**The ambiguity band value: `ambiguity_band = 0.20`** (i.e. `capped`
requires `probability_binding >= 0.80`; `uncapped` requires
`probability_binding <= 0.20`; `ambiguous` is the open interval between
them). Checked directly against this repository's own existing
threshold conventions before choosing this number: `core.prefit_
identifiability`'s four-tier `_channel_support_status()` classification
(strong/moderate/weak/very_weak) turns out to use count- and
coefficient-of-variation-based thresholds (e.g. `strong_positive_
weeks_min=60`), not a symmetric probability band — so it is NOT a
directly reusable numeric precedent for this specific band, and this
record does not claim it is. The `0.20` band is instead grounded in a
standard, widely-used convention in applied Bayesian decision-making:
classifying a posterior probability as "confident" only once it clears
an 80%/20% (four-in-five) threshold, leaving the middle 60% of
probability space genuinely "ambiguous" — a conservative, symmetric,
easily-audited choice that does not require fitting or tuning against
this repository's own data (avoiding exactly the "manufacturing cap
information absent in the data" risk `REQ-SEARCH-002` already warns
about for a different threshold). This band is deliberately NOT claimed
as a business threshold requiring Finance/Modelling sign-off — it is an
evidence-confidence convention, exactly like the existing `min_
nonbinding_periods=4`/`min_binding_periods=2`/`min_periods_per_
market=8` constants `identify_candidate_a_search` already hard-codes
with the identical "explicit conservative gate, not a claim of causal
identification" framing, even though those specific constants use a
different (count-based) form of threshold than this record's
(probability-based) one.

## Decision G: module-sharing timing

**Candidate G1 — generalise now: a shared `core.capacity` module.**
**Candidate G2 — defer generalisation until a second pathway exists.**
**Candidate G3 — approve the vocabulary now; defer the shared module.**

**Decision: G1**, but scoped precisely: the shared module
(`ancestry_mmm/core/capacity.py`) generalises exactly the two things
that ARE pathway-agnostic today — the cap-hit status vocabulary/
classification function (Decision S above) and a governed
`CapacityLimitDefinition` object shape covering the categories Decision
18 explicitly names (spend limits, delivery/exposure limits,
availability on/off, fixed commitments, minimum/maximum ranges) — while
explicitly NOT generalising `core.graph_model_compiler`'s
`capacity_constrained` structural validation to a hypothetical second
pathway that does not exist yet (see "does not" list above). This is a
narrower G1 than wp11's original framing anticipated (which considered
generalising the compiler too) — justified because Decision 18's
business requirement is specifically about capacity constraints being
usable across Scenario Planner, Optimiser, and Search reporting (data/
governance layer concerns), not about a second model-fitting pathway
existing (a much larger, unrelated undertaking this record has no
mandate to invent). `core.search_capacity` is extended (not replaced)
to consume the new module's classification function for a new field,
alongside its existing, unchanged boolean.

## Decision R4: does Candidate A's reconciliation identity generalise?

**Decision: yes, as a general contract, generalised as `verify_
capacity_reconciliation(realised, unmet, potential)`** —
`realised + unmet == potential` (renamed from Candidate A's specific
`captured_demand`/`unmet_demand`/`latent_branded_search_demand` to
pathway-neutral names) is retained as the shared identity every
capacity-constrained pathway must satisfy, grounded in source 1's
confirmation that a hard censoring/min relationship (of which this
identity is the natural conservation-of-mass consequence) is a
recognised statistical structure, not a Candidate-A-specific quirk.
`AGENTS.md`'s own "do not prescribe one exact probability distribution
or censoring mechanism... enforce the semantics and reconciliation
above, not one frozen algebraic form" caution is honoured: this record
requires the CONSERVATION identity (nothing is created or destroyed
between realised, unmet, and potential), not a specific likelihood
family or link function — a future pathway remains free to use a
different distribution while still satisfying this identity.

## What a "governed source and versioned cap-hit rule" requires

**Decision:** the cap VALUE's identity/versioning already provided by
`core.search_objects` for Candidate A specifically is sufficient for
the cap object itself; the classification RULE (the ambiguity-band
threshold and point-evaluation tolerance above) is versioned
separately, as a named constant with an explicit version comment in
`core.capacity` (mirroring how `core.seo_visibility`'s
`methodology_version` field versions a computation rule distinct from
the data it operates on) — changing the ambiguity band in the future is
a rule-version change, not a silent behavioural drift.

## Implementation

`ancestry_mmm/core/capacity.py` (new):

- `CAP_HIT_CAPPED`/`CAP_HIT_UNCAPPED`/`CAP_HIT_AMBIGUOUS`/`CAP_HIT_
  UNAVAILABLE`, `CAP_HIT_STATUSES` — the four-value vocabulary.
- `CAP_HIT_AMBIGUITY_BAND = 0.20`, `CAP_HIT_CLASSIFICATION_RULE_
  VERSION = "1.0.0"`.
- `classify_cap_hit_status` — one period's status from either a point
  binding boolean OR a posterior `probability_binding`, and an optional
  `cap_value` (`None` => `unavailable` regardless of other inputs).
- `classify_cap_hit_status_series` — vectorised, over an array.
- `CapacityLimitKind` vocabulary (`spend_limit`/`delivery_exposure_
  limit`/`availability_toggle`/`fixed_commitment`/`bounded_range`) and
  `CapacityLimitDefinition` — the governed, versioned, user-editable
  object shape Decision 18 requires, spanning Search and non-Search use
  (TV inventory, sponsorship, etc.), following `core.search_objects`'
  established lineage-identity pattern (`limit_id`/`limit_version`).
- `verify_capacity_reconciliation` — the generalised conservation
  identity (R4).

`ancestry_mmm/core/search_capacity.py` (extended, additive only): a new
`candidate_a_cap_hit_status` function computes the four-value
classification for Candidate A specifically, from its existing
`probability_cap_binding`/cap-value inputs, via `core.capacity`'s shared
function — the existing `cap_binding` boolean field and all existing
reconciliation logic are completely unchanged.

Tests: `ancestry_mmm/tests/test_capacity.py`,
`ancestry_mmm/tests/test_search_capacity.py` (new cases for
`candidate_a_cap_hit_status`, existing cases unmodified).

## Owner and status

Owner: Modelling / Platform engineering. Status: implemented and
tested, 2026-08-30, per the user's explicit 2026-08-30 authorization
delegating this technical selection (see wp11's updated text).
