# REQ-HIERARCHY-001: Shared global pooling-scale diagnostic hierarchy challenger (H2) for the current UK Model A candidate

**Status:** approved for implementation - **diagnostic-only, not a production default**
**Decision date:** 2026-08-26
**Scope:** the current UK Model A candidate's (`scripts/run_uk_production_fit.py`) outcome-level partial-pooling hierarchy only, as a gated, default-off diagnostic challenger available via `prior_config["shared_pooling_scale"]=True` in `core.hierarchical_model.build_fh_hierarchical_model`. This record does **not** approve replacing the current per-channel `sigma_pool[channel]` hierarchy as the production candidate; it authorises building, fitting, and evaluating the challenger so the analyst can compare it against the current hierarchy and the WP2.10 Overall challengers.

## Decision

The analyst reviewed WP2.10's evidence (`docs/wp2_10_remediation_evidence_20260825.md`/`docs/wp2_10_decision_package_20260825.md`: the current per-channel `sigma_pool[channel]` hierarchy sits at its `HalfNormal(0.3)` prior mean for nearly every channel in both products - 18-19 separate variance parameters estimated from only 2-3 outcome groups each, essentially uninformed by data - while the WP2.10 single-outcome Overall challengers, which remove the hierarchy entirely, converge with zero divergences but fit somewhat worse and lose `uk_dna_performance_display`'s genuine segment-level heterogeneity) and approved, as a **diagnostic-only hierarchy challenger** (WP2.11 decision 3, item H2):

1. A new hierarchy form is available, gated off by default:

   ```
   log_beta[o, c] = mu_channel[c] + sigma_pool_global * z_offset[o, c]
   ```

   where `sigma_pool_global` is **one scalar** pooling scale shared across every channel for the product/model (not one `sigma_pool[c]` per channel), `z_offset[o, c] ~ Normal(0, 1)` retains its existing per-`(outcome, channel)` shape, and `mu_channel[c]` is unchanged.

2. Enabled via `prior_config["shared_pooling_scale"] = True` in `core.hierarchical_model.build_fh_hierarchical_model`. Default `False` - every existing caller (the production fit, WP2.9/WP2.10's diagnostic scripts, every existing test) is unaffected.

3. The prior on `sigma_pool_global` is `HalfNormal(0.3)` - the **same scale** the current per-channel `sigma_pool[c]` prior already uses (`prior_config.get("pooling_sigma_prior", 0.3)`, unchanged). This is retained as **experimental continuity for this diagnostic comparison only**, not a newly optimised or searched prior - this record does not approve a broader prior search for `sigma_pool_global`.

4. The new variable is named `sigma_pool_global` (a bare scalar, `dims=()`) - **never** `sigma_pool` (which continues to mean the per-channel vector everywhere else in this codebase). This is deliberate: a persisted trace, replay path (`core.predict`, `core.attribution`), diagnostic, or attribution consumer must never be able to misinterpret one hierarchy's evidence for the other's by name collision. `beta`/`log_beta` themselves keep their existing name, dims (`("outcome", "channel")`), and shape regardless of which hierarchy produced them, so every existing downstream reader of `beta`/`log_beta` works unchanged against either hierarchy's trace.

5. Model/candidate identity is already distinguished without a new mechanism: `core.prefit_identifiability.build_prefit_fingerprints`'s `transform_config_fingerprint` is a direct hash of the whole `transform_config`/`prior_config` mapping passed to it, so `prior_config["shared_pooling_scale"]=True`'s mere presence already produces a different fingerprint from the current candidate's approved config - no second fingerprinting mechanism was created.

6. `shared_pooling_scale=True` takes precedence over `pooled_beta_reference=True` if both are ever set (checked first in `build_fh_hierarchical_model`) - not a supported combination this diagnostic was designed for, but resolved to a real, inspectable model rather than an error, and explicitly tested (`test_shared_pooling_scale_takes_precedence_over_pooled_beta_reference`).

7. **No automatic selection rule is created by this experiment.** H2's evidence (whether it removes divergent geometry, whether `sigma_pool_global` is actually learned from data, whether it retains `uk_dna_performance_display`'s segment heterogeneity, channel-contribution stability, predictive fit) is reported for analyst review (`docs/wp2_11_hierarchy_decision_package_20260826.md`) alongside the current hierarchy, H1 (`pooled_beta_reference=True`, already-approved gate), and the WP2.10 Overall challengers. **A later, separate analyst decision is required before any hierarchy - H1, H2, or the current per-channel form - becomes the production default for the UK Model A candidate.**

8. **No channel-specific exception is created.** H2 does not special-case `uk_dna_performance_display` or any other channel - whether that channel's `z_offset` values remain distinguishable from every other channel's under a single shared pooling scale is exactly what H2's evidence is meant to determine from the likelihood, not assumed.

## Rationale

See "Decision" above and `docs/wp2_10_decision_package_20260825.md` (items 2-3, 5) for the evidence this record reconciles: the current per-channel hierarchy's `sigma_pool[channel]` values are individually unidentifiable from only 2-3 outcome groups each, but a single shared scale pools information across every channel's `(outcome, channel)` deviations simultaneously - potentially recovering enough groups (2-3 outcomes × 18-19 channels) for the pooling *scale itself* to be genuinely learned from data, while `z_offset[o, c]` remains free per `(outcome, channel)` cell to express real heterogeneity (such as `uk_dna_performance_display`'s) where the likelihood supports it, unlike the WP2.10 Overall challengers' complete removal of the hierarchy.

## Explicitly not approved by this record

- Any change to the production default hierarchy for the current UK Model A candidate.
- A prior search or re-optimisation of `sigma_pool_global`'s scale.
- Treating H2 as validated, certified, or preferred before its own fit evidence is reviewed.
- Any channel-specific parameterisation exception.
- Applying `shared_pooling_scale` to any model other than the current UK Model A candidate's diagnostic evaluation.

## Affected modules

- `ancestry_mmm/core/hierarchical_model.py` (new gated diagnostic branch in `build_fh_hierarchical_model`; the existing default/`pooled_beta_reference`/lognormal branches are unchanged)
- `docs/approved_requirements/REQ-HIERARCHY-001.md` (this record)
- `docs/approved_requirements/index.json`

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_hierarchical_model.py::TestSharedPoolingScaleHierarchyChallenger::test_creates_a_scalar_sigma_pool_global_not_the_per_channel_vector`
- `ancestry_mmm/tests/test_hierarchical_model.py::TestSharedPoolingScaleHierarchyChallenger::test_default_and_pooled_beta_reference_configs_are_unaffected`
- `ancestry_mmm/tests/test_hierarchical_model.py::TestSharedPoolingScaleHierarchyChallenger::test_log_beta_and_beta_retain_outcome_and_channel_dims`
- `ancestry_mmm/tests/test_hierarchical_model.py::TestSharedPoolingScaleHierarchyChallenger::test_shared_pooling_scale_draws_are_finite`
- `ancestry_mmm/tests/test_hierarchical_model.py::TestSharedPoolingScaleHierarchyChallenger::test_shared_pooling_scale_takes_precedence_over_pooled_beta_reference`
- `ancestry_mmm/tests/test_hierarchical_model.py::TestSharedPoolingScaleHierarchyChallenger::test_transform_config_fingerprint_distinguishes_h2_from_the_current_candidate`

## Human traceability

Derived from the analyst's WP2.11 instruction (2026-08-26), decision 3 ("H2: one shared pooling scale across channels within a product"), reviewing WP2.10's evidence (`docs/wp2_10_remediation_evidence_20260825.md`, `docs/wp2_10_decision_package_20260825.md`).
