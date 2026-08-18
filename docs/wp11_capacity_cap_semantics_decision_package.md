# Capacity and cap semantics decision package (Work Package 11)

Status: decision support only. No code changes accompany this package;
no candidate approach below is enabled, selected, or implemented by it.

## Decision required

`docs/specification_authority.md` already lists "Capacity and cap
semantics" as "No approved requirement/decision yet", pointing to
`AGENTS.md`'s "Capacity and cap invariants" section as the standing
business/mathematical invariant no `REQ-CAP-001` record yet translates
into an approved modelling contract. `REQ-GRAPH-001` independently
confirms the gap's exact boundary: its own governed-edge-role table
states `capacity_constrained` is "Supported only by the explicit
Candidate A Search linked engine for its authorised Search structure
(`REQ-SEARCH-002`); unsupported for every other structure." This package
is the missing decision-support document.

The exact decision required after this package is reviewed is:

> Select and approve one production contract for pathway-agnostic
> capacity/cap semantics (or explicitly reject all candidates below and
> request another package), covering: whether `AGENTS.md`'s four-value
> cap-hit vocabulary ("capped / uncapped / ambiguous / unavailable") is
> defined once as a reusable typed contract or left to each pathway to
> define independently; what "ambiguous" and "unavailable" concretely
> mean under posterior uncertainty and missing governed cap data
> respectively - neither of which Candidate A's current implementation
> represents; and what a "governed source and versioned cap-hit rule"
> concretely requires beyond the object identity/versioning `core.
> search_objects` already provides for Candidate A specifically.

This is intentionally not chosen by the coding agent. `core.search_
capacity` continues to be the only implemented capacity-constrained
pathway, using its own narrow two-value (binding/non-binding) boolean,
and `core.graph_model_compiler` continues to reject `capacity_
constrained` for every structure other than Candidate A's authorised
Search shape, pending review of this package.

## Why this is a modelling and governance question, not an engineering one

`AGENTS.md`'s "Capacity and cap invariants" section states seven business/
mathematical rules deliberately in the abstract - "Do not prescribe one
exact probability distribution or censoring mechanism for this beyond
what an approved model specification requires - enforce the semantics and
reconciliation above, not one frozen algebraic form." Inspecting the one
existing concrete implementation against those rules shows real,
specific gaps between the abstract invariant and what has actually been
built, each raising a genuine open question:

1. **Cap-hit status is currently binary, not the required four values.**
   `core.search_capacity.candidate_a_forward` (lines 306-328) computes
   `cap_binding=np.isclose(paid, cap, rtol=1e-8, atol=1e-8)` - a strict
   boolean on a single point evaluation. `AGENTS.md`'s invariant requires
   four states: capped, uncapped, ambiguous, unavailable. Neither
   "ambiguous" (what does a status *between* clearly-binding and
   clearly-non-binding mean when `paid` is evaluated per posterior draw,
   as Candidate A's own reconciliation is - a binding-probability
   distribution near the boundary is a fundamentally different concept
   from an `np.isclose` tolerance check on one number) nor "unavailable"
   (a market/period with no governed cap value at all, as opposed to a
   cap of zero or infinity) has any representation in the current code.
   Defining both is a statistical/semantic judgement call, not a missing
   `if` branch.
2. **Whether this becomes one reusable contract or stays per-pathway.**
   `EDGE_ROLE_CAPACITY_CONSTRAINED` is already generic graph vocabulary
   (`core.graph_model_compiler`'s edge-role enum), but the only compiler
   logic that exists for it (`_validate_candidate_a_structure` and
   neighbouring functions) is Candidate-A-specific structural validation,
   not a pathway-agnostic capacity/cap module. Whether a second future
   capacity-constrained pathway should share one governed capacity/cap
   contract (mirroring how `REQ-COVERAGE-001` or `REQ-GRAPH-001`
   generalise a cross-cutting concern once) or each pathway should define
   its own is an architectural decision with real tradeoffs on both
   sides, not resolvable by inspecting Candidate A alone since it is
   still the only concrete example.
3. **What "governed source and versioned cap-hit rule" requires.**
   `core.search_capacity` already treats the cap as one of `core.
   search_objects`'s governed, versioned Search object bindings (`"the
   governed cap object"`, referenced at `core.search_capacity.py:240`),
   giving it *object* identity and versioning. Whether that already
   satisfies `AGENTS.md`'s "versioned cap-hit *rule*" language (the
   thresholding/tolerance logic that decides binding, e.g. the `rtol`/
   `atol` constants currently hard-coded at lines 326/384), or whether the
   rule itself also needs independent governance/versioning distinct
   from the object it applies to, is not decided anywhere today.
4. **Whether the reconciliation identity generalises unchanged.**
   Candidate A's `captured_demand + unmet_demand == latent_demand`
   identity (lines 310-317) is enforced structurally and validated by
   `test_search_capacity.py`. Whether this exact algebraic form is the
   *general* contract `AGENTS.md` intends for any future capacity-
   constrained pathway, or whether `AGENTS.md`'s explicit "do not
   prescribe one exact... mechanism" caution means a different pathway
   could reconcile differently (e.g. a distribution rather than a point
   split), is not decided by this package either.

## Candidate approaches to the cap-hit status vocabulary

### Candidate S1 - Extend the existing boolean to a four-value enum, threshold-based

Replace `cap_binding: np.ndarray` (boolean) with a four-value status per
period (`CAPPED`/`UNCAPPED`/`AMBIGUOUS`/`UNAVAILABLE`), where `AMBIGUOUS`
is assigned when a posterior-draw-level binding-probability estimate
(mirroring `core.search_capacity.CapBindingSummary.probability_cap_
binding`, already computed at lines 486-537) falls inside an approved
tolerance band around 0.5, and `UNAVAILABLE` is assigned when no governed
cap value exists for that market/period at all (distinct from a
supplied, finite cap of zero). Directly extends code that already
exists; requires approving a specific ambiguity-band threshold - an
explicit statistical judgement call, not a default this package
supplies.

### Candidate S2 - Distributional cap-hit status, no single point label

Report the full per-draw binding-probability distribution (already
computed by `CapBindingSummary`) as the primary evidence, with the four-
value label (if shown at all) derived as a disclosed summary rather than
the primary artefact - consistent with this program's own established
"disclose evidence, avoid a single fabricated verdict" precedent (`core.
calibration_comparison`'s explicit no-verdict-field requirement,
`REQ-CALIB-001`). Most consistent with that precedent; leaves
`AGENTS.md`'s literal "capped / uncapped / ambiguous / unavailable"
four-value language to be read as a set of disclosed evidence facets
rather than one mandatory categorical field, which is itself an
interpretation this package does not resolve.

### Candidate S3 - Keep per-pathway status definitions, no shared vocabulary

Conclude that the four-value vocabulary is a documentation-level
invariant each capacity-constrained pathway implements in its own idiom
(Candidate A's current binary check, refined or not, being one valid
idiom), with no single shared enum/type across pathways. Requires no new
shared module; risks two future pathways representing "ambiguous" or
"unavailable" incompatibly, undermining `AGENTS.md`'s evident intent that
this is one invariant, not pathway-specific vocabulary.

## Candidate approaches to whether the contract is pathway-agnostic or Candidate-A-scoped

### Candidate G1 - Generalise now: a shared `core.capacity` (or similarly named) module

Extract a pathway-agnostic capacity/cap contract (the reconciliation
identity, cap-hit status vocabulary, and cap-object governance
expectations) into its own module that `core.search_capacity` is
refactored to consume, and that `core.graph_model_compiler` can validate
against for any future `capacity_constrained` edge, not only Candidate
A's. Directly answers `REQ-GRAPH-001`'s own "unsupported for every other
structure" boundary; generalising from exactly one existing concrete
example (Candidate A) risks encoding accidental Candidate-A-specific
assumptions into a supposedly pathway-agnostic contract - a real design
risk this package does not resolve.

### Candidate G2 - Defer generalisation until a second concrete pathway exists

Leave `core.search_capacity` as Candidate A's own module, unrefactored,
and defer any shared/generalised capacity contract until a second
capacity-constrained pathway is actually proposed and can be compared
against Candidate A's shape - avoiding premature abstraction from a
single example. Consistent with this repository's general engineering
discipline against speculative abstraction; leaves `REQ-CAP-001` itself
unimplementable in any pathway-agnostic sense until that second pathway
exists, which may not be scheduled.

### Candidate G3 - Approve the vocabulary/invariants now; defer the shared module

Approve `AGENTS.md`'s cap-hit vocabulary and reconciliation-identity
language itself as binding on Candidate A today (i.e. resolve Candidate
S1/S2/S3 above and require Candidate A to implement the chosen one), while
explicitly deferring the G1-vs-G2 module-sharing question until a second
pathway exists. Decouples the two decisions cleanly; still requires this
package's S-candidate decision to be made regardless of G1/G2/G3.

## What this package does not decide

- Which cap-hit status candidate (S1/S2/S3) is approved, including any
  specific ambiguity-band threshold S1 would need.
- Whether the capacity/cap contract is generalised into a shared module
  now (G1), deferred (G2), or partially deferred (G3).
- What a "versioned cap-hit rule" requires beyond the cap object's own
  existing identity/versioning in `core.search_objects`.
- Whether `core.search_capacity`'s existing reconciliation identity
  (`captured + unmet == latent`) is the intended general form for any
  future pathway, or specific to Candidate A's structure.
- Any specific `core.search_capacity`, `core.graph_model_compiler`, or
  new-module code change - both are untouched by this package.
- Whether resolving this gap is scheduled ahead of or behind any other
  open work-package item - this package only supplies the missing
  decision-support document; it does not reprioritise the program.

## Owner and status

**Owner:** Modelling (cap-hit status semantics, reconciliation-identity
generality), Data Science / Platform engineering (module-sharing
architecture, cap-object governance mechanics).

**Status:** Decision-support package only. `core.search_capacity`
continues to use its existing binary `cap_binding` check and `core.
graph_model_compiler` continues to reject `capacity_constrained` for
every structure other than Candidate A's authorised Search shape, exactly
as before, pending review of this package.
