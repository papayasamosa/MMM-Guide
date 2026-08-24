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

Evidence records carry data, model-window, channel-set, and transform-config
fingerprints, a diagnostic version, and a generation timestamp. Any mismatch
is stale. The project bundle persists the evidence through its existing
diagnostics directory, so older bundles remain importable without inferring
new evidence.

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

Neither upstream package provides Ancestry's governed support matrix,
outcome-scale review states, stale evidence fingerprints, or the explicit
separation between a short sampler smoke test and production convergence.
Those are the narrow custom services implemented here. No upstream private
internals are copied and no upstream dependency is added by this feature.
