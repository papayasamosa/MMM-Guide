# Pre-fit identifiability evidence

The application now calculates a reusable, diagnostic-only pre-fit evidence
object from arbitrary model-ready data. It is implemented in
'ancestry_mmm/core/prefit_identifiability.py' and exposed to the workflow
through 'ancestry_mmm/application/prefit_identifiability_service.py'.

## Evidence boundary

The support layer reports target-window support, zero runs, distinct positive
values, positive-value scale, effective geometric adstock support, response
domain coverage relative to the current K reference, and the current
decay/K/S prior summaries. It also records optional posterior and synthetic
recovery evidence when a caller supplies it. The result is a
transform-identifiability diagnostic, not a channel-selection rule. It never
deletes, merges, zero-fills, re-roles, or excludes a channel.

The prior-predictive layer has two explicit levels:

1. finite/non-finite evidence; and
2. descriptive observed-scale quantile and ratio evidence.

No observed-scale threshold policy is applied unless the caller supplies a
versioned 'PriorPredictiveThresholdPolicy'. Without one, finite evidence is
'wide_but_reviewable' and remains review-recommended. Optional component
draws are summarised when available; unavailable decomposition is recorded
explicitly.

Short sampler screens use separate state semantics. Zero divergences pass a
divergence smoke test, but a short screen does not establish production
convergence or create a production candidate.

## Freshness and persistence

Evidence records carry data, model-window, channel-set, transform-config,
candidate-specification, prepared-frame, and causal-graph fingerprints. If an
identity object is unavailable, its explicit `None` value is fingerprinted so
later availability/change makes evidence stale rather than weakening the
contract. A diagnostic version and generation timestamp are also retained.
Any mismatch is stale. The project bundle persists the evidence through its
existing diagnostics directory, so older bundles remain importable without
inferring new evidence.

## Deterministic pre-fit screen

`ancestry_mmm/core/prefit_screening.py` and
`ancestry_mmm/application/prefit_screening_service.py` provide the required
deterministic layer in the official pre-fit sequence. It uses expanding,
time-respecting folds and fold-local media transform references to compare
baseline/context-only with baseline/context-plus-media Ridge and ElasticNet
surrogates. A bounded geometric-adstock/Hill grid is used for diagnostic
geometry only. The persisted result includes channel and transform stability,
residual/autocorrelation metrics, a future-to-past timing refutation,
same-sample safeguards, fingerprints, and a retained-but-empty analyst
rationale field.

The screen is explicitly `diagnostic_only` and
`official_eligibility: false`. It cannot select or remove channels, modify
priors, create posterior evidence, or approve attribution, CPA/ROI, curves,
planning, or optimisation. `review_recommended` remains the safe default until
an analyst records the required rationale. The Model Setup control retains that
text as review evidence, while the official-eligibility flag remains false; no
rationale is invented by the application.

## Upstream alignment and custom gap

The production model remains custom PyMC/PyTensor Model A. Existing prior
predictive sampling uses the supported PyMC API
'pymc.sample_prior_predictive'; this pre-fit module only analyses its returned
draws and does not reimplement sampling.

The closest upstream references consulted for the modelling boundary are:

- 'pymc-devs/pymc', pinned by this repository to PyMC 5.28.5, for prior
  predictive sampling and inference-data shapes.
- 'pymc-labs/pymc-marketing', pinned by this repository to PyMC-Marketing
  0.19.4, for the conceptual MMM transformation and response-curve boundary.
- 'scikit-learn/scikit-learn', pinned by this repository through `uv.lock`,
  for the public `Pipeline`, `StandardScaler`, `Ridge`, and `ElasticNet` APIs
  used by the deterministic screen.

Context7 resolution was recorded for `/pymc-devs/pymc`,
`/pymc-labs/pymc-marketing`, and `/scikit-learn/scikit-learn`. Its catalogue
exposed PyMC-Marketing 0.18.1 and scikit-learn 1.7.1 documentation at review
time; the repository lock remains authoritative for the installed PyMC-
Marketing 0.19.4 and scikit-learn 1.9.0 runtime. The implementation uses only
documented public APIs; local tests against the locked runtime are the
compatibility check for this repository.

Neither upstream package provides Ancestry's governed support matrix,
outcome-scale review states, stale evidence fingerprints, or the explicit
separation between a short sampler smoke test and production convergence.
Neither provides this exact leakage-safe, transformation-aware pre-fit
evidence contract; that is the narrow custom service implemented here. No
upstream private internals are copied and no upstream dependency is added by
this feature.
