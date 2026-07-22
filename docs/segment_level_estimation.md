# Pathway-Masked Coefficient Estimation (PR G1)

Design record for making `core.pathways`' `MediaOutcomePathway` catalogue (PR F - schema only)
*operational*: it now controls which `(outcome, channel)` coefficients are actually estimated in both
Model A (`core.hierarchical_model`) and Model C (`core.market_specific_model`), rather than being
calculation-adjacent metadata. This is the first PR in the reprioritised roadmap that changes fitted
coefficients.

## The four pathway roles, now operational

`core.pathways.resolve_pathway_masks(outcome_ids, channels, pathways, *, dna_channel_idx, dna_outcome_id,
direct_dna_outcome_ids, dna_lag_weeks)` resolves a project's pathway catalogue (plus the legacy DNA
direct/halo defaults for any cell it doesn't cover) into a `ResolvedPathwayMasks` - the single source of
truth both PyMC builders and every NumPy replay/attribution module read:

```text
primary_direct           - full weight, standard prior, undelayed saturated media
active_cross_product      - a distinctly regularised (HalfNormal, shrunk toward zero) effect on a
                             shared cross-product lag - generalises the old DNA halo pathway to any
                             channel a pathway catalogue routes there
exploratory_cross_product - the same structure as active_cross_product but a *tighter* prior sigma by
                             default (0.08 vs 0.25) - "strongly shrunk toward zero"
excluded                  - zero contribution, deterministically (absent from every matmul, not merely
                             a tight prior)
```

A cell can be `primary_direct` **and** `active_cross_product`/`exploratory_cross_product`
simultaneously (the DNA cross-sell outcome's own DNA channel, by legacy default) - both terms are
estimated and summed, exactly reproducing the old "gets both a direct and a halo term" treatment.

## Legacy-default equivalence

**With no pathway catalogue configured, `resolve_pathway_masks` reproduces this codebase's exact
pre-PR-G1 behaviour**, proven by construction and by the migrated `TestPredictMuDirectHaloSeparation`/
`TestShapleyDirectHaloSeparation` test suites (which encode the OLD expected direct/halo behaviour and
still pass unchanged against the NEW masked implementation):

- A non-DNA channel is `primary_direct` for every outcome (unconstrained beta, as always).
- A DNA channel + a kit-only outcome (member of `direct_dna_outcome_ids`, not `dna_outcome_id`) is
  `primary_direct` only.
- A DNA channel + `dna_outcome_id` is `primary_direct` **and** `active_cross_product` (the one cell
  with two terms).
- A DNA channel + any other outcome is `active_cross_product` only.

An explicitly configured `MediaOutcomePathway` for a specific `(channel, target_outcome_id)` pair fully
replaces the legacy default for that one cell - a deliberate, honest simplification (not a silent
difference): the pathway's own `lag_weeks` field is stored/validated but not yet read by fitting (every
active/exploratory cell shares one `cross_product_lag_weeks`, generalising `dna_lag_weeks` - per-pathway
custom lag values remain a documented future extension).

## Construction (both PyMC builders, identical calls)

```python
pathway_masks = resolve_pathway_masks(
    outcome_ids, channels, pathway_catalogue,
    dna_channel_idx=dna_channel_idx, dna_outcome_id=dna_outcome_id,
    direct_dna_outcome_ids=direct_dna_outcome_ids, dna_lag_weeks=dna_lag_weeks,
)
primary_mask = pt.constant(pathway_masks.primary_matrix(outcome_ids, channels))
eta_primary = pm.math.dot(sat_media, (beta * primary_mask).T)        # Model A
# eta_primary = pt.sum(sat_media[:,None,:] * beta_by_market_idx * primary_mask[None,:,:], axis=2)  # Model C

active_cells = pathway_masks.active_cells(outcome_ids, channels)
exploratory_cells = pathway_masks.exploratory_cells(outcome_ids, channels)
cross_product_lag_media = _market_grouped_lag(sat_media, market_bounds, pathway_masks.cross_product_lag_weeks)
# a per-cell HalfNormal strength vector, scattered into an (outcome, channel) matrix, masked-matmul
# against cross_product_lag_media - same pattern for active_cross_product_strength and
# exploratory_cross_product_strength, with sigma=0.25 / 0.08 respectively.
```

Both builders call the exact same `resolve_pathway_masks(...)` with identical arguments and construct
`eta_primary`/`eta_active`/`eta_exploratory` via the same masked-matmul pattern - eliminating a
pre-existing risk this refactor also fixes as a side benefit: the old DNA direct/halo logic was
independently duplicated in `hierarchical_model.py`, `market_specific_model.py`, `predict.py`,
`market_specific_predict.py`, `attribution.py` and `market_specific_attribution.py`, with no structural
guarantee the six copies stayed in sync. `test_hierarchical_model.py`'s
`test_both_builders_resolve_pathway_masks_identically` source-inspects both builders for the same key
lines, so a future edit to one that forgets the other fails loudly rather than silently diverging.

## `FHModelMeta.pathway_masks`

`pathway_masks: Optional[ResolvedPathwayMasks] = None` - `None` is the "not supplied" sentinel, not a
literal empty-masks value: `__post_init__` auto-resolves the legacy default (empty catalogue) whenever
it's left `None`, so a hand-built `FHModelMeta` (a test fixture, or a bundle saved before PR G1 with no
such key at all) never silently replays against an all-cells-excluded `ResolvedPathwayMasks()` - the
exact bug that field default would otherwise cause. An *explicitly* passed `ResolvedPathwayMasks` -
including a genuinely empty one, e.g. a catalogue that excludes every channel for every outcome - is
never overwritten; only the true "wasn't supplied at all" case triggers the auto-resolve.

## NumPy replay: `FHPosteriorParams.pathway_strength`

`halo_strength: Dict[str, float]` (per-outcome only) is replaced by `pathway_strength: Dict[str,
Dict[str, float]]` (per `[outcome_id][channel]`) - since a cell is never in both `active_cross_product`
and `exploratory_cross_product` simultaneously, the two named PyMC deterministics
(`active_cross_product_strength`, `exploratory_cross_product_strength`) are safely summed at extraction
time (`core.predict.extract_pathway_strength`, shared by both Model A and Model C extraction) into one
unified lookup - replay code doesn't need to know which sub-role produced a given cell's value, only
which cells (`pathway_masks.active_cells()`/`.exploratory_cells()`) to apply it to.

`predict_mu`/`predict_mu_market_specific` mirror the PyMC construction exactly: a masked matmul against
`sat_media` for the primary mask, a separate masked matmul against `cross_product_lag_media` (lagged by
`pathway_masks.cross_product_lag_weeks`) scaled by `pathway_strength`. The steady-state functions
(`steady_state_outcome_response`, `generate_channel_curve` and their Model C equivalents) use
`_pathway_weight(meta, params, outcome_id, channel)` instead: at constant spend, the primary
(undelayed) and cross-product (lagged) media converge to the identical value, so the combined weight
(`1.0` if `primary_direct`, plus `pathway_strength` if also/instead active or exploratory) can be
applied to one steady-state term directly. `core.attribution`/`core.market_specific_attribution`'s
`_channel_log_terms` functions use the same masked construction for the Shapley decomposition's
per-channel log-terms.

## Explicitly out of scope for PR G1

Per the reprioritised roadmap's exact instruction: the full scenario planner, sequential (weekly)
optimisation, an automated geo-test pipeline, a brand-equity module, the DNA composition model, and the
UI theme evaluation remain untouched. Per-pathway custom `lag_weeks` (vs. one shared
`cross_product_lag_weeks`) is a documented future extension, not built here.

## Verification

See `test_pathways.py` (`resolve_pathway_masks` legacy-default equivalence and explicit-override
tests), `test_hierarchical_model.py`/`test_market_specific_model.py` (Model A/Model C parity,
source-inspection), `test_predict.py`/`test_market_specific_predict.py`/`test_attribution.py`/
`test_market_specific_attribution.py` (migrated `halo_strength` -> `pathway_strength` fixtures, still
proving the same four legacy invariants), `test_predict_pathway_masks.py` (excluded-pathway zero
contribution, active/exploratory replay parity, the `None`-sentinel auto-resolution), and
`test_simulation_recovery.py` (Shapley attribution recovers the true relative channel strength under
correlated spend). Both PyMC model builders were also re-verified offline (not committed to the test
suite, matching this codebase's established "no real PyMC build in the committed suite" convention) to
build cleanly and evaluate to a finite log-probability at the initial point, with excluded and
exploratory pathways configured.
