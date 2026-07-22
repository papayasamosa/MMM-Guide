# Media-Outcome Pathway Catalogue (PR F)

Design record for `core.pathways` and the outcome-schema additions that accompany it - the explicit
statement of which media channels this project believes affect which outcomes, through what kind of
relationship, ahead of the pathway-specific estimation work (PR G) that will actually use it.

**Scope of PR F: schema, validation, persistence, fingerprinting, fit-time metadata and drift detection
only.** No new model equation is added; no fitted coefficient changes; `ModelSpec.dna_channels` and
`FHModelMeta.direct_dna_outcome_ids`/`kit_only_outcome_ids`/`halo_eligible_outcome_ids`
(`docs/dna_fh_causal_structure.md`) remain the only structural inputs the PyMC model builders actually
read. This PR proves the pathway schema can already describe the relationships a future estimation PR
needs - including relationships to outcomes that don't have a computed value yet - before that PR
exists to consume it.

## Why this exists

`dna_channels` only distinguishes "direct" vs. "halo" for DNA-targeted media - it says nothing about
FH media's own effect on FH outcomes, nothing about *confidence* in a given relationship, and nothing
about whether a given effect should be trusted for planning vs. shown only as an exploratory,
tight-prior estimate. There was no single place a project's actual beliefs about "which channel drives
which outcome, and how" were written down. `MediaOutcomePathway` is that place.

## The schema

```python
MediaOutcomePathway(
    channel="DNA_Media",
    source_product="DNA",
    target_outcome_id="dna_new_kit",
    role="primary_direct",
    lag_type="none",
    lag_weeks=None,
    prior_scale=1.0,
    include_in_attribution=True,
    include_in_planning=True,
    evidence_status="untested",
    pathway_id="a1b2c3d4e5f6",  # auto-generated if left blank
)
```

`pathway_id` is this pathway's stable identity (auto-generated via `uuid4` if left blank) - what a
re-save matches on to update in place rather than duplicate, and what drift detection compares across
a fit; it is deliberately *not* part of the fingerprint payload (see "Fingerprinting" below).
`channel`/`source_product` describe which media is doing the influencing; `target_outcome_id` is
validated against the project's *current* outcome catalogue - not a fixed enum - so a pathway can
target any outcome_id an analyst has captured, including the planned net-bill-through/DNA
purchase-type outcomes below, the moment a matching `OutcomeDefinition` exists (even manually, ahead of
any dedicated transformation computing it).

### Pathway roles

```text
primary_direct           - the channel's own product's main effect
active_cross_product      - a trusted, currently-estimated cross-product effect (e.g. DNA media's halo
                             onto FH cross-sell)
exploratory_cross_product - a speculative effect under a tight prior, not yet trusted for planning
                             (include_in_planning should be False)
excluded                  - explicitly ruled out, kept as a documented decision rather than silently
                             absent from the catalogue
```

Ancestry's documented default expectations (`core.pathways.DEFAULT_PATHWAY_EXPECTATIONS`, reference
data only - not enforced):

```text
DNA media   -> DNA kits:     primary_direct
DNA media   -> FH outcomes:  active_cross_product (delayed halo)
FH media    -> FH outcomes:  primary_direct
FH media    -> DNA kits:     exploratory_cross_product (tight prior, planning=false)
```

`lag_type`/`evidence_status` are free text (`core.pathways.SUGGESTED_LAG_TYPES`/
`SUGGESTED_EVIDENCE_STATUSES` are UI suggestions only, not a validated closed vocabulary - the roadmap
doesn't specify one for either field, unlike `role`). `include_in_attribution`/`include_in_planning`
are independent downstream-eligibility flags, matching the four-flag eligibility pattern
`core.outcomes.outcome_eligibility` already established, rather than overloading `role` to control
everything.

## Validation

`validate_media_outcome_pathways(pathways, channels=None, outcome_ids=None)` rejects (never raises):
missing/duplicate `pathway_id`; an unknown `channel` (checked only when `channels` is given, the same
opt-in convention as `validate_outcome_definitions`'s `available_columns`); an unknown `source_product`;
an unknown `target_outcome_id` (checked only when `outcome_ids` is given); an unknown `role`; a negative
`lag_weeks`; a non-positive `prior_scale`; and a duplicate `(channel, target_outcome_id)` pair - at most
one pathway should describe a given channel's relationship to a given outcome.

## Fingerprinting, persistence and fit-time metadata

`pathway_catalogue_fingerprint_payload(pathways)` is calculation-*adjacent* (not yet calculation
-relevant - nothing reads it to compute anything) configuration, fingerprinted the same way
`core.funnel.FunnelLink` is: `core.fingerprint.fingerprint_model_spec`'s `media_outcome_pathways`
parameter. The payload is sorted and keyed by `(channel, target_outcome_id)` - the pair
`validate_media_outcome_pathways` treats as the natural uniqueness key - deliberately *excluding*
`pathway_id`: two independently-constructed but logically-identical catalogues (auto-generated
`pathway_id`s differ) must fingerprint identically, the same reasoning
`core.promotions.PromotionEvent.event_id` is never itself fingerprinted.

Persisted as `config/media_outcome_pathways.json` in the project bundle
(`core.persistence.export_project`/`import_project`), following the established "absent means legacy,
not corrupt" convention: a bundle exported before PR F simply has no such file, `import_project` reports
`media_outcome_pathways: None`, and every downstream reader treats `None` as "no pathway catalogue
configured", not an error.

`FHModelMeta.pathway_catalogue_at_fit` (populated identically by both `build_fh_hierarchical_model` and
`build_fh_market_specific_model`, via a pure pass-through added to
`data.preprocessor.prepare_fh_modeling_frame`'s `media_outcome_pathways` parameter) captures the exact
catalogue in effect when a fit was built - purely so a future estimation PR (PR G) can compare "what
pathways were assumed at fit time" against the live catalogue, without waiting for that PR to add the
capture mechanism too. `core.persistence.reconstruct_model_state` restores it to real
`MediaOutcomePathway` instances on reimport, mirroring `outcome_catalogue_at_fit`'s treatment.

## Drift detection

`core.pathways.pathway_drift_status(pathway, fit_time_pathway)` mirrors
`core.outcomes.outcome_drift_status`, keyed by `pathway_id`: `"Fitted and current"` (unchanged),
`"Changed since fit"` (any tracked field differs), `"New since fit"` (not part of the fit's captured
metadata), `"Removed since fit"` (no longer in the current catalogue).
`pathways_drift_dataframe(pathways, model_meta)` builds a full table across the union of both
catalogues. Unlike the outcome catalogue's drift status (which the Scenario Planner treats as
*blocking*), pathway drift is **informational only everywhere it's shown** (Structure, Diagnostics,
Project Export) - the pathway catalogue does not yet drive fitting, so there is nothing for a stale
pathway to make wrong.

## UI

The Structure page's "Media-outcome pathway catalogue (optional, forward-looking)" section (below
Funnel links) is an `st.data_editor` table, one row per pathway, seeded from and saved back to session
state alongside the rest of the page's Save handler - validated against the page's own `channels`
multiselect and the live outcome catalogue's `outcome_id`s. `pathway_id` is hidden from the editor
(auto-managed, like `event_id` on the DNA promotion calendar). Diagnostics and Project Export show
pathway drift informationally when a fitted model and a non-empty pathway catalogue both exist.

## Outcome-schema additions (planned metric keys, aggregation_type, date_basis, maturity_required)

These accompany the pathway catalogue because a pathway needs to be able to target the expanded future
outcome set explicitly, and because "prevent unsafe aggregation" needs the schema in place before any
transformation produces the values it would otherwise misuse.

### Planned metric keys

`core.outcomes.METRIC_REGISTRY` gained seven new entries - no computation pipeline exists for any of
them yet (see "Explicitly out of scope" below):

```text
fh_net_billthrough_count       - count, Family History, unit "bill-through subscriber"
fh_net_billthrough_rate        - rate, Family History, unit "proportion" - NOT allowed in the
                                  optimiser or as a CPA denominator (MetricDefinition.
                                  allowed_in_optimiser/allowed_in_cpa = False)
fh_gsa_finance_date            - count, Family History, unit "GSA" - the finance-date-recognised GSA
                                  series, distinct from a marketing-attributed net-bill-through count
dna_kit_sale_self_activated    - count, DNA, unit "kit"
dna_kit_sale_gifted_activated  - count, DNA, unit "kit"
dna_kit_sale_unactivated       - count, DNA, unit "kit"
dna_kit_sale_total             - count, DNA, unit "kit" - a distinct key from the pre-existing
                                  dna_kit_sale (kept unchanged for backward compatibility), for the
                                  roll-up an analyst may fit *instead of* the three atomic categories
```

`MetricDefinition` gained `aggregation_type` (`"count"`/`"rate"`/`"currency"`/`"index"` -
`core.outcomes.AGGREGATION_TYPES`), `allowed_in_optimiser` and `allowed_in_cpa` - catalogue-level
policy, not a per-outcome override: `fh_net_billthrough_rate` is the only built-in metric with
`aggregation_type="rate"`, and it is the only one with `allowed_in_optimiser=allowed_in_cpa=False`.

### OutcomeDefinition: aggregation_type, date_basis, maturity_required

`aggregation_type` derives from `metric_key` via the registry, the same pattern `unit` already uses
(a custom/unrecognised metric_key defaults to `"count"` - the safe default matching every outcome
fit so far, not a guess about a new business meaning). `validate_outcome_definitions` now rejects a
`"rate"`-aggregation outcome that resolves eligible for the official total or optimisation (via
`outcome_eligibility`) - the roadmap's explicit "do not use net bill-throughs and net bill-through rate
as synonyms" / "do not allow rate outcomes into count totals or count-based CPA" - forcing an analyst
to mark a rate outcome `role="secondary"` (or an equivalent explicit override) rather than leaving it at
the `"primary"` default, which would otherwise make it eligible for the official total.

`date_basis` (one of `core.outcomes.DATE_BASIS_VALUES` - `event_date`/`signup_date_attributed`/
`billing_date`/`purchase_date`/`activation_date` - or `None`) records which real-world date a row's
value is indexed by: a net-bill-through count is indexed by `signup_date_attributed` even though the
underlying billing event happened later. `maturity_required` (`Optional[bool]`) flags an outcome whose
most recent periods are right-censored (a bill-through cohort that hasn't had time to mature). Neither
field is read by any transformation yet - they are schema/validation-only metadata, exactly like
`aggregation_type`, `date_basis` and `maturity_required` are deliberately **not** included in the
outcome catalogue fingerprint or drift-tracked fields: nothing downstream computes anything from them
today, so editing one does not (yet) invalidate an approval - the same "descriptive, not
calculation-relevant" reasoning `core.market_config.MarketDescriptors` is excluded from the fingerprint
for (`core/fingerprint.py`'s `_model_relevant_market_config` docstring). If a future PR makes either
field drive a real calculation, that is itself a fingerprint-breaking change to make at that time.

### Outcome reconciliation groups

`core.pathways.OutcomeReconciliationGroup(group_id, component_outcome_ids, relation, total_outcome_id)`
describes an arithmetic relationship that should hold across already-modelled outcomes - "DNA total =
self-activated + gifted-activated + unactivated" (`relation="sum"`), or "FH net bill-through rate = FH
net bill-through count / FH eligible sign-ups" (`relation="ratio"`).
`reconciliation_group_diagnostics(group, values_by_outcome_id)` is a diagnostic-only check (never
raises, reports `None` rather than a guessed value for anything it can't evaluate) - it does **not**
feed a constrained estimation step, per the roadmap's explicit "initially use this for validation and
diagnostics, not necessarily constrained estimation." **Deliberately not fingerprinted** - the same
"descriptive, not calculation-relevant" reasoning as `aggregation_type`/`date_basis` above; nothing
downstream reads a reconciliation group to compute anything yet.

## Explicitly out of scope for PR F

Per the roadmap's exact instruction, none of the following are built in this PR - only the schema that
will eventually need them:

- The net-bill-through transformation itself (`build_net_billthrough_cohorts` and the cohort-maturity/
  censoring/offer-rule machinery the roadmap specifies) - no bill-through cohort is actually computed.
- The DNA activation classifier (`classify_dna_purchase_type`) - no purchase is actually classified as
  self-activated/gifted-activated/unactivated from raw purchase/activation data. **The most important
  caveat this schema already encodes for when that classifier exists:** an unactivated kit is not
  definitively a gift - `unactivated` must remain its own atomic metric_key
  (`METRIC_KEY_DNA_KIT_SALE_UNACTIVATED`); a `gift_or_unactivated` roll-up would only ever be an
  explicitly labelled reporting assumption, never a silent substitute.
- The constrained FH funnel model (sign-ups -> conversion probability -> net bill-through count) -
  `core.funnel`'s diagnostics-only treatment (PR E.2) is unchanged; no transition model is added.
- The DNA composition model (total-plus-conditional-composition) comparing atomic vs. total-only DNA
  outcome modelling - not evaluated, not built.
- Causal DAG / expert-specified variable roles, Brand Search mediation modes, the dynamic
  (weekly-sequential) scenario planner, and the UI theme evaluation - all remain future roadmap items,
  untouched by this PR.

## Recommended sequencing (not part of this PR)

```text
PR F.1: outcome-date and maturity semantics - as-of date, cohort maturity validation, offer
        bill-through rules, activation classification rules, wired into the data pipeline (not just
        the schema this PR adds)
PR G:   pathway-specific estimation - separate/regularised coefficient families per pathway role,
        starting with FH media -> FH net bill-through count, DNA media -> DNA kit total, DNA media ->
        FH net bill-through halo, FH media -> DNA kit total (exploratory)
PR G.1: optional DNA composition model - only after real-data review, comparing total-only vs.
        atomic-outcome vs. total-plus-conditional-composition modelling
```
