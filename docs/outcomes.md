# Outcome Schema

Design record for `core.outcomes` - the generalised outcome catalogue that lets the tool describe
*what's being measured* (product, segment, metric, source column, value weight) as explicit
dimensions, rather than assuming every measurable outcome is a Family History segment.

**`outcome_id` is the model's canonical identity dimension (PR E, "make `OutcomeDefinition` the
canonical modelling schema" - see `docs/decision_log.md`), not `segment`.** Every fitted model, curve,
attribution, scenario, and persisted bundle keys on `outcome_id`, never on `segment` membership. This
is what makes it possible to fit two distinct KPIs on the *same* customer segment - e.g. a Family
History **sign-up** (`outcome_id="fh_new_signup"`) and a Family History **GSA**
(`outcome_id="fh_new_gsa"`), both `segment="New"` - as two independent outcome_ids with independent
fitted response curves, rather than conflating them because they happen to share a segment name.
`segment` remains a *descriptive* grouping field (which customer segment this outcome belongs to), not
a unique key.

**PR E.2 closes the gap PR E.1 left open: display-string metric matching, role-only eligibility, and a
still-mandatory legacy Structure workflow.** `OutcomeDefinition.metric_key` (derived from a small
canonical `METRIC_REGISTRY`, never guessed from `product` alone) replaces exact-string matching on
`metric` for every built-in selector; `include_in_default_reporting`/`include_in_official_total`/
`include_in_value`/`include_in_optimisation` replace `role="primary"`-only gating with four
independently-configurable flags; the outcome catalogue editor is now the Structure page's only
workflow, not a second source of truth layered on a still-mandatory legacy FH-segment mapper. See
"Canonical metric keys and unit defaults", "Four independent eligibility flags" and "The catalogue is
the only Structure workflow" below, and `docs/decision_log.md`'s PR E.2 entry for the full list of
eleven changes (promo/control-by-outcome-id, funnel-coherence diagnostics, CPA scope metadata,
optimiser target hardening, first-class drift status, replayable promotion events).

**PR E.1 closes the gap PR E left open: aggregation code still keyed off "not a DNA-kit outcome"
rather than the catalogue's actual `product`/`metric` labels.** The core model could already fit a
sign-up and a GSA as independent outcome_ids, but `evaluate_scenario`/`optimize_scenario`/curve
generation still summed "every non-DNA-kit outcome_id" into a total labelled `fh_gsa` - silently
folding the sign-up into it. `core.outcomes.select_outcome_ids`/`fh_gsa_outcome_ids`/
`fh_signup_outcome_ids`/`dna_kit_sale_outcome_ids` are now the single place every total/CPA/objective
in this codebase goes to decide "which outcome_ids belong in this named number", always from explicit
`product`+`metric` (+ `role`) selectors read off `FHModelMeta.outcome_id_to_product`/`_metric`/`_role`
(the fit-time catalogue), never from "isn't a DNA-kit outcome". See "Product-aware outputs" below.

## Why this exists

Before this schema, "outcome" meant exactly one thing: an entry in `ModelSpec.segment_outcomes`,
implicitly a Family History GSA column. That's correct for what the fitted model predicts today, but
it can't represent DNA kit purchases - a genuinely different business outcome (a product sale, not a
Family History signup) with its own economics - or two distinct KPIs (a sign-up funnel step and its
downstream GSA) on the same customer segment. `core.outcomes.OutcomeDefinition` adds an explicit
`product` dimension (`"Family History"` or `"DNA"`) alongside `segment`, `metric`, `source_column`, and
an optional `value_weight`, so the catalogue can describe all of these without forcing the data into a
shape built for one-outcome-per-segment.

## Scope boundary: captured always, modelled once mapped

`ModelSpec.segment_outcomes` is now purely a **migration source** - `core.outcomes.fh_outcomes_from_spec`
derives an equivalent outcome catalogue from it for any project that predates this schema. The actual
frame-preparation and model-building path (`data.preprocessor.prepare_fh_modeling_frame`,
`core.hierarchical_model.build_fh_hierarchical_model`, `core.market_specific_model.
build_fh_market_specific_model`) takes an explicit outcome catalogue (`outcomes=`, a
`List[OutcomeDefinition]`) as its structural input, not `spec.segment_outcomes` directly. DNA-product
outcomes are **opt-in**: mapping one on Structure: Segments & Markets does not, by itself,
retroactively change any existing fit, but the next time the modelling frame is prepared on Model
Configuration, `core.outcomes.dna_kit_outcome_columns` feeds the mapped DNA outcome_id(s) into
`prepare_fh_modeling_frame`'s `outcomes` parameter, and from there into the model builders'
`direct_dna_outcome_ids` - DNA-targeted media then gets full, direct response on that outcome_id, not
the shrunk-toward-zero halo pathway other outcomes get. See `docs/dna_fh_causal_structure.md` for the
full equation-level treatment and how double counting between DNA kit sales and FH cross-sell is
avoided.

`core.outcomes.outcome_requires_opt_in(outcome)` reflects the *automatic-vs-opt-in* distinction
specifically - `True` for any non-`"Family History"`-product outcome (today, any DNA outcome), since
FH is the only kind that's part of every fit with no extra step. It is a static, type-level question
("does this *kind* of outcome ever need a config step?") answerable from the outcome alone.

Whether a *specific* past run actually included a given outcome is a different, run-aware question -
answered by `core.outcomes.outcome_was_modelled(outcome, model_meta)` (`True` iff `outcome.outcome_id`
is in the given `FHModelMeta.outcome_ids` - `None` for `model_meta` always means `False`, never an
error - keyed on `outcome_id`, never `segment`, since two outcomes can share a segment and still need
to be distinguishable: a sign-up outcome must not read as "modelled" just because its sibling GSA
outcome on the same segment was) - and, more granularly, `core.outcomes.outcome_status(...)`, which
returns one of six states (`OUTCOME_STATUSES`): `Configured`, `Included in prepared frame`, `Included
in fitted run`, `Missing source column`, `Excluded`, `Stale after configuration changes`. A single
collapsed boolean can't distinguish "mapped but never fit" from "excluded from this fit on purpose"
from "fit before, but its source column has since disappeared" - `outcome_status` can, so every place
the outcome catalogue reaches the UI (Structure page, project report) shows this richer status rather
than a boolean, and a DNA row is never presented as if it's unconditionally influencing every fit's
outputs.

As of PR E, exclusion is a **persisted property of the outcome itself** -
`OutcomeDefinition.included_in_fit` (plus an optional free-text `exclusion_reason`) - not session-only
state: `prepare_fh_modeling_frame` filters to `included_outcomes(outcomes)` internally, and a
reimported project now reconstructs the *exact* set of outcomes that were included at fit time,
closing the persistence gap the pre-PR-E `excluded_outcome_ids` session-state mechanism left open.

As of PR E.1, the Structure page's general **outcome catalogue editor** (an `st.data_editor` table,
one row per outcome) replaces the legacy per-segment "one weekly GSA column" mapper as the actual
saved source of truth - the legacy FH segment mapper and DNA-column mapper below it still exist as
convenient defaults that seed the table, but what gets persisted is the edited table's rows, converted
straight to `OutcomeDefinition`s. This is what makes it possible to actually *configure* both `FH /
New / Sign-up` and `FH / New / GSA` (not just, in principle, fit them) - the old mapper could only ever
produce one GSA-labelled outcome per segment. `included_in_fit` is now an editable checkbox column in
this same table, replacing the old separate "exclude this DNA outcome" multiselect.

## The schema

```python
OutcomeDefinition(
    outcome_id="fh_new_signup",
    product="Family History",
    segment="New",
    metric="Sign-up",
    source_column="Signup_New",
    unit="sign-up",
    value_weight=None,
    role="funnel_intermediate",
)

OutcomeDefinition(
    outcome_id="fh_new_gsa",
    product="Family History",
    segment="New",             # same segment as the sign-up above - a distinct outcome_id, not a conflict
    metric="GSA",
    source_column="GSA_New",
    unit="GSA",            # derived default - "GSA" for Family History, "kit" for DNA
    value_weight=180.0,    # LTV - optional
    value_currency="USD",  # optional - the currency value_weight is denominated in (PR E.1)
    role="primary",        # default
)

OutcomeDefinition(
    outcome_id="dna_new_kit",
    product="DNA",
    segment="New Customer",
    metric="Kit sale",
    source_column="DNA_Kit_New_Customer",
    unit="kit",
    value_weight=90.0,     # value per kit - optional
    role="primary",
    included_in_fit=True,  # persisted exclusion flag - see "Scope boundary" above
    exclusion_reason=None,
)
```

`outcome_id` is the stable identity every fitted model, curve, attribution, scenario, and persisted
bundle keys on - it is never re-derived from `segment`. `product` is one of
`core.outcomes.FAMILY_HISTORY` / `core.outcomes.DNA`. `metric` is free text, but three canonical
values (`core.outcomes.METRIC_GSA`/`METRIC_SIGNUP`/`METRIC_KIT_SALE` - `"GSA"`/`"Sign-up"`/`"Kit
sale"`) are what every built-in selector/named total matches on (PR E.1). DNA `segment` is one of
`DNA_SEGMENT_NEW` ("New Customer"), `DNA_SEGMENT_EXISTING_FH` ("Existing FH Customer"), or
`DNA_SEGMENT_COMBINED` ("Combined") - see below. `unit`, `value_currency`, `role`, `included_in_fit`
and `exclusion_reason` are migration-safe additions: a bundle saved before these fields existed just
falls back to `unit`'s derived default, `value_currency=None`, `role`'s `"primary"` default, and
`included_in_fit=True` (`OutcomeDefinition.from_dict` filters to known dataclass fields and translates
the legacy `column` key to `source_column`, so an older/missing key never raises, it just uses the
field default) - nothing to migrate explicitly. `unit` is what every product-aware output downstream
keeps separate (see "Product-aware outputs" below); `role` is one of `OUTCOME_ROLES` (`"primary"`,
`"secondary"`, `"funnel_intermediate"`, `"diagnostic"`) and is now operational as of PR E.1 (not just
validated): `"primary"` is what every default total/objective/CPA sums over;
`"secondary"`/`"funnel_intermediate"`/`"diagnostic"` are each excluded from the corresponding default
total (see `core.outcomes._primary_role_only`'s docstring for the exact rule per role) unless a caller
asks for them explicitly. `included_in_fit` remains the separate axis controlling fitting eligibility -
`role` never affects whether an outcome is part of a fit, only how its numbers are aggregated
afterwards.

A validation heuristic (`_implies_conflicting_metric_label`) string-matches `outcome_id`/`source_column`
against `metric` and flags an outcome whose id/column implies "signup" while its metric says "GSA" (or
the reverse) - a guard against exactly the mislabelling risk two distinct KPIs on one segment could
otherwise introduce. It is a heuristic (string patterns, not data semantics), documented as such.

## Backward compatibility: every project has a catalogue, not just ones that set one up

`core.outcomes.resolve_outcome_definitions(outcome_definitions, segment_outcomes, segment_ltv)` is
the single entry point every caller (Structure page, project report, persistence) uses to get "this
project's current outcome catalogue":

- If the project has an explicitly saved outcome set (any project that has been through the
  Structure page's outcome-catalogue save since this schema shipped), that wins.
- Otherwise - every project created before this schema existed, or that has never touched the DNA
  outcomes section - `core.outcomes.fh_outcomes_from_spec(segment_outcomes, segment_ltv)` derives an
  equivalent, correct FH-only set live from `ModelSpec`. A project is never left with "no outcome
  catalogue"; it just may not have any DNA outcomes mapped yet.

This is what makes the schema backward compatible with every existing FH-only project bundle without
a migration step: there is nothing to migrate, because the FH-only case is always derivable from data
that already exists.

## Explicit FH DNA cross-sell target (PR E.1)

The model builders used to infer which outcome_id is the FH DNA cross-sell outcome (the halo
pathway's target) by substring-matching outcome_ids for `"dna"` - with DNA-product kit-sale outcomes
now also in the catalogue (e.g. `dna_new_kit`, which also contains "dna"), that heuristic is genuinely
ambiguous and was never validated to point at a Family History outcome at all. `ModelSpec.
fh_dna_cross_sell_outcome_id` is now an explicit, persisted config field (set on the Structure page,
alongside the general outcome catalogue editor); `core.outcomes.validate_fh_dna_cross_sell_outcome_id`
checks it exists among the included outcomes, belongs to Family History, and is not a DNA-product
kit-sale outcome (which has no halo pathway onto itself). `build_fh_hierarchical_model`/
`build_fh_market_specific_model` now **raise** if a fit has DNA-targeted channels configured and no
`dna_outcome_id` is resolvable - substring-based inference is no longer used as a runtime fallback. For
a legacy project that predates this field, `core.outcomes.infer_legacy_fh_dna_cross_sell_outcome_id`
offers the same substring heuristic as a one-time **migration suggestion** only (never called from the
model-building path itself) - the Structure page shows it as a visible warning the analyst must
confirm or override, not a silent default.

## DNA kit outcomes: split vs. combined

The target shape is two separate DNA outcomes - kit purchases from new customers vs. from existing
Family History customers - because they have different economics (a new-customer kit purchase is an
acquisition event; an existing customer's is a cross-sell) and, once DNA response equations exist,
different causal links back to FH. `core.outcomes.dna_outcomes_from_columns` builds this from mapped
data columns.

Where source data can't support that split, a single combined column is an explicit, visible
fallback (`DNA_SEGMENT_COMBINED`) - not a silent approximation. `validate_outcome_definitions` rejects
mixing a combined outcome with split ones in the same catalogue, and every place the catalogue is
displayed shows `segment = "Combined"` plainly rather than pretending it's one of the two specific
segments.

## Data capture: Structure: Segments & Markets

The "DNA outcomes (optional)" section on the Structure page lets an analyst map either the split
columns or a combined column, with a per-outcome value weight. On save, the page builds the full
catalogue (`fh_outcomes_from_spec(...) + dna_outcomes_from_columns(...)`), validates it
(`validate_outcome_definitions`), and stores it in session state - then renders it back as an outcome
catalogue table (`outcomes_to_dataframe`) with the run-aware `status` column (see "Scope boundary"
above), so what's captured vs. what's actually driving the fitted model is never left for the analyst
to infer.

This is deliberately part of the existing Structure page, not a new workflow step - it's additional,
optional data capture alongside the FH segment mapping already there, not a new stage in the guided
workflow.

## Product-aware outputs (PR E.1: metric-aware, not just product-aware)

Every response/CPA/scenario/optimisation output that could combine Family History GSAs, Family
History sign-ups, and DNA kit sales keeps them separate instead - the instruction document's "do not
expose a generic total volume that adds kits and GSAs" / "CPA must identify its denominator"
requirements, and the audit-confirmed `volume_objective_mixes_units` defect this closed. PR E's fix
was product-aware only (`meta.kit_only_outcome_ids`, "not a DNA-kit outcome" = FH GSA) - PR E.1
replaces that with genuinely metric-aware selectors, since a fit can now have both an FH sign-up and
an FH GSA outcome, and "not a DNA-kit outcome" would silently include both in one `fh_gsa` total.

`core.outcomes.select_outcome_ids(model_meta, *, product=None, metric=None, unit=None, role=None)` is
the central selector - filters `model_meta.outcome_ids` by explicit dimensions read from
`FHModelMeta.outcome_id_to_product`/`_metric`/`_unit`/`_role` (populated from the exact catalogue a
fit was built from, `outcome_catalogue_at_fit`). Three named totals build on it, each applying the
`role == "primary"` default (see above) unless `include_non_primary=True`:

- `fh_gsa_outcome_ids(meta)` - `product=Family History, metric=GSA`.
- `fh_signup_outcome_ids(meta)` - `product=Family History, metric=Sign-up`.
- `dna_kit_sale_outcome_ids(meta)` - `product=DNA, metric=Kit sale`.

**Legacy fallback:** a `FHModelMeta` with no catalogue metadata at all (reconstructed from a bundle
exported before `outcome_catalogue_at_fit` existed, or hand-built without it) has
`outcome_id_to_product == {}` for every outcome_id - `fh_gsa_outcome_ids` falls back to "every
outcome_id that isn't structurally DNA-kit-only" (`meta.kit_only_outcome_ids`), preserving this
codebase's pre-PR-E.1 behaviour exactly for a fit with no distinct sign-up outcome to disambiguate
from; `fh_signup_outcome_ids` returns `[]` for such a fit (a legacy fit never had one).

From there: `core.predict.generate_channel_curve`/`core.market_specific_predict.
generate_market_channel_curve` split `overall_response` into `fh_response` (GSA-metric only, not "any
non-DNA-kit outcome"), `fh_signup_response` (new column), and `dna_response`, each summing only its own
selector's outcome_ids. `core.media_units.compute_cpa_by_product` (never `compute_cpa`'s bare
`"overall_response"` default on a curve that genuinely mixes products - it raises unless the caller
passes `allow_mixed=True`) computes `avg_cpa`/`cost_per_fh_gsa`, `fh_signup_avg_cpa`/
`cost_per_fh_signup`, and `dna_avg_cpa`/`cost_per_dna_kit` against their respective response columns.
`core.optimization.evaluate_scenario`'s `fh_gsa`/`fh_signups`/`dna_kits`/`avg_cpa`/
`fh_signup_avg_cpa`/`dna_avg_cpa`/`total_value` columns, and `core.optimization.VALID_OBJECTIVES`
(`"fh_gsa"`, `"fh_signups"`, `"dna_kits"`, `"weighted_mix"`, `"expected_value"` - no generic "maximise
volume") all follow the same discipline. See `docs/dna_fh_causal_structure.md` and
`docs/decision_log.md` for the full treatment.

### Value weights are never silently defaulted to 1.0

A *partial* `ltv`/value-weight dict (some outcome_ids priced, others not) used to have missing entries
silently treated as weight `1.0` when computing `value`/`total_value` - turning a raw sign-up/GSA/kit
count into a fake dollar figure. As of PR E.1, a missing entry in a non-empty `ltv` makes that row's
`value` `None`/`NaN`, and `evaluate_scenario`'s output carries a `total_value_is_complete` flag (`False`
whenever any outcome_id that month had no value weight) so a caller can show an explicit
incomplete-value warning rather than silently under-counting. An **entirely omitted** `ltv` is not this
defect - it is the documented "no $-weighting requested at all" case, where `value` is simply raw
predicted units (uniform weight 1.0), unchanged from this function's behaviour before PR E.1.
`core.optimization`'s `"expected_value"` objective goes further and fails closed: it raises if any
eligible (role="primary", or `target_outcome_ids` if given) outcome_id has no finite, non-negative
`ltv` entry, rather than silently zero- or one-weighting it.

## Persistence

`config/outcome_definitions.json` in the project bundle (`core.persistence.export_project` /
`import_project`), following the same "absent means legacy, not corrupt" convention as
`market_spec_config.json` and `model_type.json`: a bundle exported before this schema existed simply
has no such file, `import_project` reports `outcome_definitions: None`, and every downstream reader
calls `resolve_outcome_definitions` rather than assuming the key is populated.

`core.persistence.reconstruct_model_state` rebuilds a reimported project's modelling frame from the
*same* outcome catalogue the original fit used - `resolve_outcome_definitions(imported.get(
"outcome_definitions"), ...)`, filtered to outcomes whose `source_column` is still present in
`transformed_data`, passed as `prepare_fh_modeling_frame`'s `outcomes=` argument (which itself filters
to `included_in_fit=True` via `included_outcomes()`). Because `included_in_fit` is now persisted on
each `OutcomeDefinition` rather than being session-only state, a reimported project reconstructs the
*exact* set of outcomes that were included at fit time - both the pre-PR-E "reconstruction silently
drops DNA-kit segments" defect and the "excluded_outcome_ids isn't persisted" gap are closed by the
same change: exclusion is now data the bundle carries, not a preference the session held.
`outcome_catalogue_at_fit` on `FHModelMeta` (round-tripped through the bundle as part of `model_meta.json`,
restored to real `OutcomeDefinition` instances on import) additionally records the *exact* catalogue a
fit was built from, for future staleness-detection use.

**The full canonical outcome catalogue IS part of the model-specification fingerprint (PR E.1).**
`direct_dna_outcome_ids` alone (PR E) only covered DNA-kit outcome_id membership - it did not catch
adding/removing a non-DNA FH outcome, changing sign-up to GSA, changing unit, source column, role,
inclusion, or the value weight used in planning, any of which changes what a fit computes without
changing `direct_dna_outcome_ids` at all. `core.fingerprint.fingerprint_model_spec`'s
`outcome_catalogue` parameter closes this: pass
`core.outcomes.outcome_catalogue_fingerprint_payload(outcomes)` (sorted by `outcome_id`, keeping only
the calculation-relevant fields - `outcome_id`/`product`/`segment`/`metric`/`unit`/`source_column`/
`role`/`included_in_fit`/`value_weight`/`value_currency`) - every production call site fingerprints
the fitted model's own `meta.outcome_catalogue_at_fit`, not the project's *current* (possibly
since-edited) catalogue, so the fingerprint always reflects what was actually fit. `direct_dna_outcome_ids`
is kept alongside it (a different, pathway-structural concept - see `docs/dna_fh_causal_structure.md`).
Every pre-existing approval is invalidated by upgrading to this fingerprint version, the same
"adding a genuinely model-relevant field is an intentional breaking change" pattern used throughout
this log.

## Exact fit-time drift detection

`outcome_status` (above) only detects a mapped source column *disappearing* - it cannot tell "the
mapping changed to a different, still-present column" from "unchanged". `core.outcomes.
outcome_drift_status(outcome, fit_time_outcome, available_columns=None)` closes this gap by comparing
the *current* catalogue entry against the exact `OutcomeDefinition` a specific fit was built from
(`FHModelMeta.outcome_catalogue_at_fit`, looked up by `outcome_id` via
`outcome_catalogue_at_fit_by_id`), across every tracked field (`source_column`/`product`/`segment`/
`metric`/`unit`/`role`/`included_in_fit`/`value_weight`). Returns exactly one of `DRIFT_STATUSES`:
`Fitted and current`, `Excluded from next fit`, `Changed since fit`, `Missing source column`, `New
since fit`, `Removed since fit`. `outcomes_drift_dataframe(outcomes, model_meta)` builds a full table
across the union of the current and fit-time catalogues (so a since-removed outcome still gets a row).

## Project report

The report's "Outcomes" section (`core.report._outcomes_section`) lists the full catalogue via
`resolve_outcome_definitions` and states plainly how many outcomes are Family History (modelled) vs.
DNA (captured, not yet modelled) - available at any point in the workflow, like every other report
section.

## PR E.2: semantic hardening

### Canonical metric keys and unit defaults

`OutcomeDefinition.__post_init__` used to default every Family History outcome's `unit` to `"GSA"`
regardless of metric - wrong for a sign-up outcome. `core.outcomes.METRIC_REGISTRY` maps a stable
`metric_key` (`METRIC_KEY_FH_GSA`/`_FH_SIGNUP`/`_DNA_KIT_SALE`/`_CUSTOM`) to a `MetricDefinition
(metric_key, display_name, default_unit, product)`; `metric_key` is derived from `metric` in
`__post_init__` *before* the unit default is resolved, and only a recognised metric_key gets a default
unit at all - `METRIC_KEY_CUSTOM` gets none, so a custom metric must set `unit` explicitly or
`validate_outcome_definitions` flags it.

`core.outcomes.normalize_metric_key(metric)` migrates a small, explicit table of known display
variants (`"Signup"`, `"Signups"`, `"Sign Up"`, `"Kit Sale"`, `"kit sales"`, ...) to their canonical
key, case/whitespace-insensitively - anything not on that table falls back to `METRIC_KEY_CUSTOM`,
never a fuzzy guess into a business KPI. Every built-in selector (`select_outcome_ids`,
`fh_gsa_outcome_ids`, `fh_signup_outcome_ids`, `dna_kit_sale_outcome_ids`,
`official_total_outcome_ids`) filters on `metric_key`, not the free-text `metric` display string, so a
user typing a display variant no longer silently disappears from named totals and objectives.
`FHModelMeta.outcome_id_to_metric_key` carries this at fit time, populated identically by both
`build_fh_hierarchical_model` and `build_fh_market_specific_model`.

### Four independent eligibility flags

PR E.1 gated every default total on `role == "primary"` only - a Family History sign-up marked
`funnel_intermediate` was fitted but invisible from the default `fh_signups` total and its own CPA,
because `role` was overloaded to control every downstream behaviour at once. `OutcomeDefinition` now
has four independent, optional flags - `include_in_default_reporting`, `include_in_official_total`,
`include_in_value`, `include_in_optimisation` (each `Optional[bool]`, `None` meaning "use the role
default") - resolved by `core.outcomes.outcome_eligibility(outcome)` against
`_ROLE_ELIGIBILITY_DEFAULTS`:

```text
primary:             reporting=True  official_total=True   value=True   optimisation=True
secondary:            reporting=True  official_total=False  value=True   optimisation=False
funnel_intermediate:  reporting=True  official_total=False  value=False  optimisation=False
diagnostic:            reporting=False official_total=False  value=False  optimisation=False
```

A funnel-intermediate sign-up therefore still appears in its own `fh_signup_outcome_ids`/sign-up CPA
(`include_in_default_reporting=True`) but is excluded from `official_total_outcome_ids` - the stricter
selector official GSA/sign-up totals must use. `eligible_outcome_ids(model_meta, flag)` is the general
selector every one of the four flags goes through; it reads `FHModelMeta.outcome_id_to_eligibility`
when present (fit-time catalogue), falling back to re-deriving it live from `outcome_id_to_role` for
legacy/hand-built fixtures with no eligibility metadata at all.

### The catalogue is the only Structure workflow

The Structure page used to require a mandatory "FH segment -> weekly GSA column" mapper *and*
maintain the general outcome catalogue editor alongside it - two sources of truth for the same fitting
input. The mandatory mapper was removed; the catalogue editor is now seeded from two optional,
clearly-labelled "Quick-start wizard" expanders (`Create standard FH GSA outcomes`, `Add DNA kit
outcomes`) - after seeding (or starting from a blank catalogue), every edit happens in the catalogue
table itself. `promo_cols`, `segment_control_cols` and `segment_ltv` (used by `ModelSpec` migration
fields and the DNA promotion calendar) are now *derived* from the live catalogue's segments, not
required separate inputs. `ModelSpec.validate()` no longer requires at least one `segment_outcomes`
mapping - `segment_outcomes` is migration-only now, populated only for bundles that predate the
catalogue. `validate_outcome_definitions` gained the actual enforcement point instead: at least one
outcome must be configured and `included_in_fit`, regardless of whether it came from the wizard or a
hand-added row.

### Promo and control mappings by outcome_id

Promotional and control configuration used to be keyed by legacy `segment` only - a sign-up and a GSA
sharing one segment automatically inherited the same segment-level controls and promotion series, even
where the business definition or timing genuinely differs between them. `ModelSpec` gained three
additive tiers: `outcome_promo_cols`/`outcome_control_cols` (keyed by `outcome_id`, take precedence
over the legacy segment-keyed `promo_cols`/`segment_control_cols` when set for a given outcome) and
`product_control_cols` (keyed by product - `"Family History"`/`"DNA"` - a new, coarser tier below
global controls). `data.preprocessor.prepare_fh_modeling_frame` resolves each outcome's promo column as
`outcome_promo_cols[oid]` if set, else the legacy segment mapping; controls are resolved additively
across all three tiers (product, legacy segment, outcome) and deduplicated. The Structure page's
"Outcome-level promo & control overrides" section (rendered only for segments with 2+ outcome_ids)
provides the explicit "apply this segment's mapping to every outcome in it" bulk-action button the
instruction document required, rather than making segment-wide inheritance implicit.

### Funnel-coherence diagnostics (not a constrained funnel model)

Sign-ups and GSAs are fitted as independent Negative-Binomial outcomes - nothing in the model enforces
`GSA <= sign-up`, and the model can produce incoherent predictions in some periods or scenarios. This
is a documented model limitation, not fixed in PR E.2 - see `core.funnel`'s module docstring and
`docs/limitations.md`. What PR E.2 adds instead: `core.funnel.FunnelLink(upstream_outcome_id,
downstream_outcome_id)` lets an analyst declare which sign-up/GSA pair forms a funnel;
`funnel_coherence_diagnostics(link, upstream_values, downstream_values, ...)` computes violation
counts/rates (downstream > upstream), implied-conversion-rate mean/range/stability, and never raises
except on a genuine array-shape mismatch; `funnel_channel_attribution_consistency` flags
sign-mismatched channel attribution between the pair's two outcome equations. Funnel links are
persisted (`config/funnel_links.json`) and fingerprinted (`fingerprint_model_spec`'s `funnel_links`
parameter, sorted by `(upstream_outcome_id, downstream_outcome_id)`). The Structure page lets an
analyst define links from the live catalogue; the Diagnostics page renders per-link warnings and
metrics against the prepared modelling frame.

### CPA denominator and spend-scope metadata

A scenario-level "cost per GSA" used to divide total scenario spend across all channels by the GSA
total - a legitimate whole-plan efficiency number, but easily mistaken for a channel-specific or
incremental CPA. `core.media_units.cpa_scope_metadata(denominator_metric, included_outcome_ids,
spend_scope, ...)` returns the explicit metadata block (denominator metric, included outcome IDs,
spend scope from `CPA_SPEND_SCOPES` - `"whole_plan"`/`"channel_incremental"`/`"observed_platform"`,
included channels, market, time window, incremental-vs-observed), validating `spend_scope` and
`incremental_vs_observed` against their allowed values. `compute_cpa_by_product` gained explicitly
scope-named alias columns (`channel_incremental_cost_per_fh_gsa`/`_fh_signup`/`_dna_kit`);
`evaluate_scenario` gained `whole_plan_cost_per_fh_gsa`/`_fh_signup`/`_dna_kit`. See
`docs/media_units_and_inflation.md`.

### Hardened optimiser target validation

Every optimisation objective now runs `_validate_target_outcome_ids` before scoring anything: an
unknown `target_outcome_id` raises; a `target_outcome_id` whose `metric_key` doesn't match the
objective's metric raises (skipped only for legacy `FHModelMeta`s with no catalogue metadata at all,
matching this codebase's established legacy-fallback convention); an outcome with
`include_in_optimisation=False` (a diagnostic role's default, or an explicit override) raises. A user
can no longer pass a sign-up outcome into `objective="fh_gsa"` and bypass metric-aware selection.
`"weighted_mix"` additionally rejects non-finite or negative weights, and rejects mixing raw units
across different `unit`s (e.g. GSAs and kits) unless the caller explicitly passes
`assume_value_scaled_weights=True` - weights are assumed to already be on a common value scale only
when the caller says so, never inferred.

### Drift status is first-class, not Diagnostics-only

`core.outcomes.has_blocking_drift(outcomes, model_meta, ...)` classifies drift as blocking
(`BLOCKING_DRIFT_STATUSES`: `"Changed since fit"`, `"Removed since fit"`) or informational (`"New
since fit"`, `"Excluded from next fit"` - a not-yet-fit addition or a deliberate exclusion isn't a
staleness problem). `components.ui.render_drift_status` is now wired into all seven pages the
instruction document named: Structure, Model Configuration, Model Training, Diagnostics, Results &
Curve Bank and Project Export show it informationally (an `st.info`/`st.warning` plus an expander with
the full field-by-field diff); **Scenario Planner blocks** (`st.stop()`) when blocking drift is
present, even with an approved, fingerprint-matching trace still in memory - planning against a
catalogue that no longer matches what was actually fit is never allowed, regardless of approval state.

### Promotion events are replayable pipeline steps

`core.promotions.PromotionEvent` gained `event_id` (stable identity, auto-generated via `uuid4` if
left blank - what a re-save matches on to update in place rather than duplicate), `product`,
`affected_outcome_ids`, `market`, and `transformation_version`. `promotion_events_to_transform_steps`/
`transform_steps_to_promotion_events` convert an event list to/from `data.pipeline.TransformStep(op=
"promotion_event", ...)` entries in the same `pipeline_steps` list the Transform Pipeline page's
manual transforms use - deliberately excluded from that page's operation dropdown, since a
`promotion_event` step is only ever produced from a structured `PromotionEvent`, never hand-built.
`apply_step`'s `"promotion_event"` branch replays one event's contribution additively onto its
segment's derived `_promo_event_{segment}` column (creating it at zero if absent), matching
`promotion_weekly_series`'s existing "overlapping promotions for the same segment compound" semantics -
replaying N per-event steps for one segment reproduces exactly what applying all N events at once
would produce.

The Structure page's Save handler persists events as `TransformStep`s (replacing every prior
`promotion_event` step with the current event list - other step types are left untouched) *in addition
to* materialising the derived column into `transformed_data` for the current session. Project Export's
import handler goes further: it drops whatever derived promo column is already sitting in the imported
parquet for a segment with a `promotion_event` step, then replays those steps fresh against the
imported `transformed_data` - so re-importing a project reproduces the derived columns from the
versioned event list, never trusting a possibly-stale value baked into the parquet.

## PR F: planned metric keys, outcome-type metadata, and the pathway catalogue

`METRIC_REGISTRY` gained seven forward-looking metric keys (Family History net bill-through count/rate,
finance-date GSA, and four DNA purchase-type keys - self-activated/gifted-activated/unactivated/total)
and `OutcomeDefinition` gained `aggregation_type`/`date_basis`/`maturity_required` - schema and
validation only, no computation pipeline exists for any of these yet. `core.pathways.
MediaOutcomePathway` is a new, separate, persisted/fingerprinted catalogue of explicit
`(channel, target_outcome_id)` relationships, designed so a pathway can already target any of these
planned outcome_ids. None of this changes what gets fitted. See `docs/media_outcome_pathways.md` for
the full design record and `docs/decision_log.md`'s PR F entry.

## Synthetic demo data

`ancestry_mmm/sample_data/generate_sample_data.py` generates `DNA_Kit_New_Customer` and
`DNA_Kit_Existing_FH_Customer` weekly count columns per market, driven by DNA-targeted media
response, seasonality (DNA kits are a strong gifting item - Christmas/New Year dominates more here
than in the FH outcomes), promotion, and kit price - a distinct synthetic series from the existing
`GSA_DNA_CrossSell` Family History signup metric, not a copy of it. This exists so the demo project
can exercise the split-outcome capture path end-to-end; it is not a causal simulation of DNA-to-FH
linkage (there isn't one yet - see the scope boundary above).
