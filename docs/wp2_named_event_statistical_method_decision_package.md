# Named-event statistical-method decision package (Work Package 2 precursor)

Status: decision support only. No code changes accompany this package;
no candidate approach below is enabled, selected, or implemented by it.
Created by Work Package 0 of `Media-Mix-Lab: Coding LLM Next Steps Post
PR #297` (2026-08-19) as the authority side of the named-event
reconciliation; Work Package 2 of the same brief supplies the
synthetic evidence each candidate is measured against.

## Decision required

The refreshed PRD (Part 6 v1.9 `1212CBD9AAC7F89F`, Part 7 v1.8
`89CF8D1FA523FA26`) defines the boundary of named-event response —
factual dates preserved, closed temporal vocabulary
(`contemporaneous`, `anticipatory`, `post_event`,
`anticipatory_and_post_event`), no reverse adstock, separation from
media/promotion/price/seasonality, future replay of the fitted
semantics — but deliberately does **not** select one universal
statistical response method. Part 6 allows fixed, partially pooled or
regularised estimated response structures and discourages
unconstrained collections of independent weekly lead dummies where
recurrence support is weak.

The decisions required after this package and the WP2 evidence are
reviewed are:

1. the event-response structure: fixed governed profile, partially
   pooled estimated structure, or regularised estimated basis;
2. the kernel/basis family for the deterministic event-relative
   transformation;
3. priors (and any regularisation strength) for estimated structures;
4. pooling/heterogeneity (market, product, outcome) policy;
5. family-specific maximum lead and lag support values;
6. validation thresholds for recurrence support, timing sensitivity
   and separation evidence (Part 7);
7. planning-eligibility thresholds (Part 7 → Part 8).

None of these is chosen here, by the coding agent, or by
`REQ-EVENT-001`/`REQ-EVENT-002`. The PRD does not allocate
event-specific decision-register IDs (there are no `EV-*` items);
decision ownership must be assigned by the human decision owners
without this package inventing identifiers.

## PRD constraints every candidate must satisfy

- The factual occurrence date/interval is never shifted to represent
  pre/post-event demand; negative event-relative periods are generated
  from the occurrence without mutating it.
- Anticipatory response is an event lead/response mechanism, never
  reverse media adstock and never a manufactured pre-event flag.
- Named-event response remains separable from promotion, price, media
  activity, media adstock and smooth (Fourier) seasonality where they
  overlap.
- A permitted lead/lag window is support only, never evidence that
  every period inside it has a material effect.
- Complexity is constrained by repeated-event support: flexible
  lead/lag profiles are restricted where the number of occurrences is
  too small for credible identification; weakly identified timing,
  magnitude or separation keeps the effect exploratory even when
  overall predictive fit improves.
- Heterogeneity (market/product/outcome) requires repeated-event
  support and validation justification.
- The same approved definition and fitted semantics must be replayable
  in future scenarios at model grain (`REQ-EVENT-002`).
- No candidate may silently reallocate a known seasonal/gifting signal
  into media, promotion or baseline terms.

## Decision dimension 1: response structure

| Candidate | Description | Main risk |
|---|---|---|
| S1 - Fixed governed profile | A human-governed, fixed relative-time weight profile per event family (e.g. step/ramp defined at review time), no estimated event parameters | Mis-specification risk; no uncertainty propagation from estimation; requires governed profiles per family |
| S2 - Low-dimensional parametric kernel | Estimated shape through a small parameter set (e.g. two- or three-parameter normal/Laplace/decay-mixture kernel over relative weeks) | Parametric bias if the true timing shape differs; prior sensitivity at small recurrence counts |
| S3 - Regularised distributed basis | Estimated coefficients over a low-rank basis (e.g. regularised spline/Fourier basis over the lead/lag window) with shrinkage toward zero/smoothness | Regularisation-prior choice; weak identifiability when occurrences are sparse |
| S4 - Unconstrained weekly lead/lag dummies | Independent coefficients per relative week | Part 6 explicitly discourages this as default with sparse recurrence; overfitting/leakage risk |

Part 6's own framing keeps S1, S2 and S3 admissible; S4 is admissible
only where recurrence support genuinely permits, and is not the
default.

## Decision dimension 2: kernel/basis family

Candidates include: piecewise-constant window profiles; low-dimensional
parametric shapes (normal, skewed-normal, Laplace, geometric-decay
mixture); penalised spline bases (B-spline, cyclic where annual
recurrence); Fourier bases over the lead/lag window. The
deterministic event-relative construction (Part 5) and the estimated
structure (Part 6) must be recorded as separately versioned artefacts:
changing the basis is a transformation-version change with staleness
consequences (`REQ-EVENT-001` section 8).

## Decision dimension 3: priors and regularisation

For estimated structures: prior families, shrinkage targets (zero,
smoothness, family-level shape), and any cross-family prior sharing
must be chosen with documented prior-predictive and sensitivity
evidence. A weak-recurrence default must exist (e.g. stronger
shrinkage or fixed-profile fallback) rather than a diffuse prior that
silently manufactures precise pre-event shapes.

## Decision dimension 4: pooling and heterogeneity

Whether the response structure is fully pooled, partially pooled, or
family/market/segment-specific, and which dimensions may vary, is a
separate choice from the response structure. The PRD requires
heterogeneity only where repeated-event support and validation
justify it.

## Decision dimension 5: family-specific lead/lag support

Maximum lead and lag per family (or per treatment class) are governed
values, not fitted defaults. Candidates must be informed by business
timing (e.g. gifting purchase lead) and by the timing-sensitivity
evidence, not by optimising in-sample fit over the window.

## Decision dimension 6 and 7: validation and planning-eligibility thresholds

Part 7 requires event-aware evidence (date integrity, recurrence
support, event-aware holdouts, stability, lead/lag and basis
sensitivity, separation from media/promotion/seasonality, synthetic
recovery) but leaves the accept/planning thresholds decision-required.
This package records the dimensions; it does not choose thresholds.

## Required evidence (Work Package 2 scope)

Synthetic DGPs must include: contemporaneous only; anticipatory only;
post-event only; combined anticipatory+post-event; event + promotion;
event + media burst; event + seasonal peak; sparse repeats (e.g. 2-3
occurrences); adequate repeats (e.g. 8+); multi-market cases; and
Model A / Model C variants. For each candidate, measure:

- event recovery (timing shape and amplitude);
- leakage into media/promotion/baseline/seasonality terms;
- posterior uncertainty and prior sensitivity;
- lead/lag window-length sensitivity;
- stability across folds/seeds;
- holdout behaviour;
- computational cost (fit and replay);
- future-replay fidelity (same definition, future factual dates).

The comparison must use the pinned runtime (PyMC 5.28.5, PyTensor
2.38.3, ArviZ 0.23.4) and official upstream APIs; any upstream
reference consulted must be recorded per the repository's
upstream-reference workflow. No MCMC belongs inside any optimisation
loop.

## Ownership

Marketing Data Science (statistical form, priors, pooling, support
windows) and Model Governance (validation and planning-eligibility
thresholds). The coding agent does not select a candidate.

## Traceability

`REQ-EVENT-001` "Explicitly excluded" and `REQ-EVENT-002` "Explicitly
excluded"; `docs/approved_requirements/index.json` (2026-08-19);
`docs/specification_authority.md` named-event overlay section.
