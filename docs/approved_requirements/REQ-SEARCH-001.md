# REQ-SEARCH-001: Search Object Separation

## PRD source

Current product-context implementation brief: Search-related signals must
never be silently collapsed into a single Brand Search/Paid Search variable.
Identified as a governance gap ahead of any Search capacity/demand modelling
work.

## Capability status

Partially implemented. `core.search_objects.SearchObjectDefinition` governs
identity, unit, scope, provenance, planning eligibility, and cross-object
validation for the first six §1 concepts; `Channel & Media Units` (page 10)
is the governance UI; `core.persistence` round-trips governed records
through project export/import (`config/search_objects.json`,
`resolve_imported_search_objects`); the Causal Graph page's "Seed nodes"
action seeds a graph node per §8's role mapping. §1.7 (residual Paid Search
incrementality) remains exactly `core.brand_search`'s existing mechanism -
untouched.

§14's last bullet (a `paid_search_cap` record must have a corresponding
`paid_search_spend`/`paid_search_delivery` record in the same market x
channel to constrain) is now closed: `SearchObjectDefinition.channel` is an
explicit, governed field (mirroring `ActivityDefinition.channel`/
`MediaInputSpec.channel`) that `validate_search_object_catalogue` uses to
resolve a cap's counterpart by exact `(market, channel)` equality - never by
name-matching. A cap with no counterpart, a wrong-channel counterpart, or
more than one cap record bound to the same `(market, channel, unit)` fails
closed with a specific `missing_cap_counterpart`/`duplicate_cap_relationship`
issue, both at the `Channel & Media Units` UI and on project import
(`resolve_imported_search_objects`). A legacy record with no `channel`
declared is quarantined on import, never fabricated a relationship.

§10's versioning contract is now closed: `SearchObjectDefinition` carries
`effective_period_start`/`effective_period_end` (mirroring
`MediaInputSpec`/`GovernedCostMapping`, validated by the same
start-must-not-be-after-end rule, malformed dates rejected via
`date.fromisoformat`) and `search_object_version` (an incrementing version
number within the `(market, search_object_id)` lineage, mirroring
`core.causal_graph.CausalGraph`'s `graph_id`/`graph_version` immutability
pattern). `core.search_objects.new_search_object_version` is the only
sanctioned way to edit a governed record - it always returns a new instance
with `search_object_version + 1` and resets `approval_status` to draft,
never mutates the record it was given, and refuses to change the lineage
identity (`search_object_id`/`market`) or set `search_object_version`
directly. `current_search_object_versions` resolves, per lineage, the
current (highest-versioned) record - deterministic and independent of input
order. `validate_search_object_catalogue`'s cross-object checks (column-alias
conflicts, cap-counterpart resolution) run only over each lineage's current
version, so a superseded historical version is never flagged as conflicting
with its own successor; `duplicate_identity` is now keyed on the full
`(market, search_object_id, search_object_version)` triple, since two
distinct versions of the same lineage are legitimate. The `Channel & Media
Units` page routes an edit to an already-saved row through
`new_search_object_version` automatically (comparing the edited row against
the previously saved record for that lineage) and keeps every version in a
`search_object_versions` history list, mirroring the Causal Graph page's
Save draft/version-history pattern; `core.search_objects.
search_object_versions_for_export`/`core.persistence.
resolve_imported_search_objects` round-trip that full version history
(never only the current record) through project export/import, mirroring
`graph_versions_for_export`/`resolve_imported_causal_graphs`.

§11's fail-closed schema contract is now closed for Search objects the same
way REQ-GRAPH-001 §10 already closed it for `CausalGraph`:
`SearchObjectDefinition.from_dict` raises `ValueError` for a `schema_version`
above `SEARCH_OBJECT_SCHEMA_VERSION` (currently 2) or a malformed
(non-integer) `schema_version`, and `resolve_imported_search_objects`
quarantines any record that raises, named by id and reason in `warnings` -
never silently accepted with its unrecognised fields dropped. A legacy
record predating schema_version 2 (no `effective_period_start`/
`effective_period_end`/`search_object_version` keys at all) is not treated
as "unknown" - it migrates to the documented defaults (no declared period,
version 1).

§13's fit-identity binding is now closed: `core.search_objects.
search_object_fit_fingerprint` is threaded into
`core.fingerprint.fingerprint_model_spec` the same way
`activity_fit_fingerprint` already is, and consumed by `core.persistence.
current_model_identity_fingerprints` and the same five pages
`activity_fit_fingerprint` feeds (Diagnostics, Results & Curve Bank,
Scenario Planner, Project Export, Official Curve Generation). Only Search
objects a fit actually *consumes* - a current-version, non-blank
`model_input_column` that exactly matches one of the fit's own
`ModelSpec.channels` - participate; registering a Search object still
changes no fitting behaviour by itself (§7, unchanged), so an unconsumed
Search object's edits never stale a fit. For a consumed object, only
`market`, `search_object_id`, `search_object_version`, `search_role`,
`source_column`, `model_input_column`, `unit`, `grain` and `product` are
fit-relevant; `channel` (governance-only, mirroring
`activity_fit_fingerprint`'s exclusion of `ActivityDefinition.channel`),
`effective_period_start`/`effective_period_end` (no model builder yet gates
consumed data by a declared window), `state`, `planning_eligibility`,
`evidence_status`, approval metadata, `currency` and `schema_version` are
administrative and excluded - editing only those on a consumed record never
stales a fit. `search_object_version` is itself fit-relevant (two versions
of the same lineage can carry identical field values, e.g. a reverted edit,
and must still fingerprint differently). No Search mathematics changed by
this closure - it is fit-identity/staleness wiring only, the same scope
boundary `activity_fit_fingerprint`/`causal_graph_structural_fingerprint`
already established.

Not yet implemented: Search demand/capacity mathematics (see Out of scope
below, unchanged).

### What already exists today (do not duplicate)

- `core.brand_search`: four analyst-chosen **treatment modes** for
  attributing an already-fitted Brand Search channel's contribution
  (`direct_channel`, `excluded`, `demand_capture_mediator`,
  `experiment_calibrated_incremental`) — this is **residual Paid Search
  incrementality** (§1.7 below) computed from an already-fitted
  `primary_direct`/`excluded` pathway. This record adds no second
  incrementality computation; §1.7 is a pointer to this existing module,
  not a new one.
- `core.media_costs.MediaInputSpec`: identity of one *model input* at
  market/channel grain (`column`, `unit`, `input_kind` —
  `monetary_spend`|`exposure`, `source`, `effective_period_*`,
  `schema_version`) — the existing spend-vs-delivery separation mechanism.
  `core.media_costs.GovernedCostMapping`/`MediaCostMapping`: the existing
  governed spend↔delivery conversion (`spend_to_media_input`/
  `media_input_to_spend`), with `approval_status`/`approved_by`/
  `approved_at`/`effective_period_*`.
- `core.activities.ActivityDefinition`: the existing governed
  activity-level object at `market × activity_id` grain, already carrying
  `activity_ownership` (`paid`|`owned`|`earned`|`external_event`),
  `model_role` (`intervention`|`mediator`|`demand_capture`|`control`|
  `event`), `economic_treatment`, `planning_eligibility`
  (`optimisable`|`scenario_only`|`fixed`|`excluded`), `source`,
  `model_input_column`, `pathway_ids`, `evidence_status`,
  `approval_status`, `change_history`, `schema_version`.
- `core.causal_graph`: node role vocabulary already includes
  `demand_capture` and `capacity_or_cap` (REQ-GRAPH-001 §4) — the graph
  domain already has a home for §1.1/§1.5/§1.6 (demand-capture roles) and
  §1.4 (capacity/cap role); no new graph vocabulary is required.
- `core.optimization.SpendConstraint`: spend-only optimiser constraints —
  does not represent an operational delivery/budget cap as a governed
  object (§1.4 is new).

This record's job is to give each of the seven concepts below an
unambiguous identity built *from* these existing mechanisms — never a
competing one.

## Requirement

### 1. The seven distinct objects

Each object below has its own semantic identity. A single raw source
column may feed at most one of these per market/channel/product — see §12
for the mappings this explicitly rejects.

#### 1.1 `search_demand` — branded-search demand or query interest

The underlying consumer intent/query-volume signal (e.g. branded query
volume, Search Console impressions, a third-party trends index) —
*upstream of any Ancestry-controlled spend or delivery*. Not itself paid,
owned, or earned media; a contextual/exogenous signal the graph may use as
a `demand_capture` node feeding downstream capture channels.

#### 1.2 `paid_search_spend` — Paid Search monetary spend

Currency spent on Paid Search media. Exactly what `MediaInputSpec
(input_kind="monetary_spend")` already represents for any paid channel;
this record does not change that mechanism, only requires Paid Search's
spend column be registered as its own `MediaInputSpec`/`ActivityDefinition`
pair distinct from §1.3–1.4.

#### 1.3 `paid_search_delivery` — Paid Search physical delivery

The physical/exposure metric Paid Search spend buys (clicks, impressions).
Exactly what `MediaInputSpec (input_kind="exposure")` already represents;
governed against §1.2 by a `GovernedCostMapping`/`MediaCostMapping`
(`spend_to_media_input`/`media_input_to_spend`) — never inferred by
assuming spend and delivery are interchangeable.

#### 1.4 `paid_search_cap` — Paid Search budget or operational cap

An operational ceiling (a daily/weekly budget cap, an inventory/impression
cap) that can bind before spend fully translates to delivery. **New** — no
existing object represents this identity today (`SpendConstraint` is an
optimiser-time spend constraint, not a registered channel-level cap
record). Represented as a `capacity_or_cap`-role node in the causal graph
(REQ-GRAPH-001 §4) when a graph is used.

#### 1.5 `organic_search_capture` — organic-search capture

Non-paid search traffic/conversions attributable to organic (unpaid,
`earned`-ownership per `core.activities.OWNERSHIP`) search results. A
`demand_capture`-role activity — it captures existing demand, it does not
create it.

#### 1.6 `direct_navigation_capture` — direct-navigation capture

Traffic/conversions from users navigating directly to a known destination
(typed URL, bookmark, app) — `owned`-ownership, `demand_capture` model
role, distinct from both organic and paid search capture.

#### 1.7 residual Paid Search incrementality

**Not a new object.** This is the existing `core.brand_search` treatment-
mode output (`demand_capture_mediator`'s `mediator_reallocation`, or
`experiment_calibrated_incremental`'s `apply_experiment_calibration`),
computed from §1.2's fitted contribution. A dependent requirement must
never introduce a second, parallel computation of this quantity.

### 2. Distinct semantic identity

No two of §1.1–§1.6 may ever share a governed record. Each is identified
by its own `(market, channel_or_activity_id, source_column)` triple —
mirroring `ActivityDefinition.activity_key`
(`market × activity_id`) and `MediaInputSpec`'s `market × channel`
grain — never inferred by name-matching or substring heuristics on a
column name.

### 3. Source mapping

Each object's `source` field (matching `ActivityDefinition.source`/
`MediaInputSpec.source`) records exactly which raw uploaded column or
external feed it comes from. §1.4 additionally records whether the cap
value itself is observed (a platform-reported daily cap) or
analyst-declared (a budget ceiling entered manually) — both are valid, but
the distinction must be visible, mirroring `core.activities.
EVIDENCE_STATUS`-style provenance.

### 4. Grain

`market × channel_or_activity_id`, weekly (this app's fitted cadence) —
identical to `MediaInputSpec`/`ActivityDefinition`'s existing grain. No
object in §1 introduces a new grain.

### 5. Unit

- §1.1 `search_demand`: an index or count (platform-defined; never assumed
  commensurable with spend or clicks without an explicit, governed
  conversion — none exists today, and none is introduced by this record).
- §1.2 `paid_search_spend`: currency (`MediaInputSpec input_kind=
  "monetary_spend"`).
- §1.3 `paid_search_delivery`: an exposure count (clicks/impressions;
  `MediaInputSpec input_kind="exposure"`).
- §1.4 `paid_search_cap`: currency or exposure count, matching whichever
  unit the cap actually constrains (a spend cap vs a delivery cap are
  different §1.4 records, never conflated).
- §1.5/§1.6: a response/conversion count in the model's existing outcome
  units — never a spend or exposure unit (neither is paid media).

### 6. Model role

Per `core.activities.MODEL_ROLES`: §1.1/§1.5/§1.6 →
`demand_capture`; §1.2 → `intervention` (or a `core.brand_search` treatment
mode, per existing mechanics); §1.3 → not itself a separate model role —
delivery is descriptive context for §1.2's fitted spend coefficient via
`MediaCostMapping`, never independently fit; §1.4 → not a `model_role` at
all (§8 below — it is a constraint/context object, not a fitted
predictor).

### 7. Future role

Governed on `Channel & Media Units` (page 10), and seedable as typed graph
nodes on the Causal Graph page (§8). Registering a Search object changes no
fitting behaviour by itself - it is not yet read by either model builder
(no `model_input_mapping` wiring into `resolve_pathway_masks_preferring_graph`
or the legacy pathway catalogue); that remains a future, explicitly-scoped
step, not an implicit consequence of registration.

### 8. Graph role

Per REQ-GRAPH-001 §4's existing node-role vocabulary: §1.1/§1.5/§1.6 →
`demand_capture`; §1.2 → `intervention`; §1.4 → `capacity_or_cap`. §1.3 is
descriptive (delivery/cost-mapping context), never a graph node on its
own. No new node or edge role is required.

### 9. Planning eligibility

Per `core.activities.PLANNING_ELIGIBILITY`: §1.2 may be `optimisable`
(it is ordinary paid spend); §1.1/§1.5/§1.6 must never be `optimisable`
(`ActivityDefinition.__post_init__` already rejects `optimisable` for a
`demand_capture` model role — this record relies on that existing
invariant, not a new one). §1.4 is a constraint on §1.2's optimisation,
never itself an optimisable target — a dependent requirement defining how
an optimiser reads a `paid_search_cap` record is explicitly out of scope
here (§13).

### 10. Versioning

Every object in §1 carries `schema_version` and `effective_period_start`/
`effective_period_end`, mirroring `MediaInputSpec`/`GovernedCostMapping`.
An edit is a new version, never an in-place mutation of an approved
record — the same immutability pattern REQ-GRAPH-001 §2 already requires
for `CausalGraph`.

### 11. Persistence

Round-trips through project export/import (`core.persistence.
export_project`/`import_project`) the same way `activity_definitions`,
`media_input_specs`, and `media_cost_mappings` already do — a dependent
requirement's bundle field, not a new persistence mechanism. A malformed or
unknown-schema imported record fails closed (quarantined, reported by id),
consistent with `resolve_imported_causal_graphs`'s existing contract.

### 12. Lineage

Every §1 record's `source`/`change_history` (mirroring
`ActivityDefinition.change_history`) must make it possible to answer "which
raw column, and which prior version, produced this value" without
re-deriving it from the raw data — the same traceability
`ActivityDefinition` and `MediaInputSpec` already provide for other
governed objects.

### 13. Stale-state effects

Changing a §1 record's mapping (source column, unit, or grain) stales
every fit/curve/scenario that consumed it, via the existing
`activity_fit_fingerprint`/`core.fingerprint.fingerprint_model_spec`
mechanism (already fingerprints `activity_fit_fingerprint`) — a dependent
requirement must wire new Search-object fingerprints into that same
mechanism, never build a second invalidation path.

### 14. Validation for incompatible mappings

A dependent requirement's validator must reject at minimum:

- a monetary/currency column mapped as §1.1 `search_demand` (demand is not
  spend);
- a click/impression column mapped as §1.4 `paid_search_cap` unless the
  cap is explicitly declared as a delivery cap (§5) — never assumed;
- an organic-traffic column (§1.5) mapped as §1.3 `paid_search_delivery`
  (organic traffic is not something Paid Search spend bought);
- any single source column mapped to more than one of §1.1–§1.6
  simultaneously (§2);
- a §1.4 cap record with no corresponding §1.2 or §1.3 record in the same
  `market × channel` to constrain.

Each rejection must be a specific, attributable message — never a silent
drop — mirroring `core.causal_graph.validate_causal_graph`'s and
`core.activities.ActivityDefinition.__post_init__`'s existing "reject with
a specific reason" contract.

## Out of scope (explicitly, for this and the dependent implementation
requirement)

- Latent demand estimation (inferring `search_demand`'s "true" level from
  observed proxies).
- Censoring/capacity equations (what happens mathematically when §1.4 is
  approached or exceeded).
- Cap-hit probability.
- Unmet demand (spend or delivery that would have occurred absent the
  cap).
- Joint upstream-media/cap optimisation (an optimiser reasoning about §1.2
  and §1.4 together).
- Generic interaction terms as a substitute for mediation — a dependent
  requirement must use the causal graph's `mediated` edge role
  (REQ-GRAPH-001 §5, not yet engine-supported — see that record's
  "Unsupported edge/node roles today") once available, never approximate
  mediation with an interaction term.

No Search mathematics (demand, capacity, incrementality, or optimisation)
is implemented by this record or by REQ-SEARCH-002.

## Affected modules

- `docs/approved_requirements/REQ-SEARCH-001.md` (new)
- `docs/approved_requirements/index.json` (new entry)

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

## Migration impact

None. No existing schema, model, or persisted artefact changes as a result
of this record — it defines identity and governance contract only. A
dependent requirement (REQ-SEARCH-002) implements the domain/persistence
representation against this contract.

## Unresolved decisions

- Whether `search_demand` (§1.1) is ever populated from a real external
  feed for this product, or remains a graph-vocabulary placeholder with no
  production data source — deferred to the dependent implementation
  requirement; must not be assumed available.
- Exact `paid_search_cap` (§1.4) record shape (single ceiling value vs a
  time-varying schedule) — deferred; §13's exclusions apply regardless of
  which shape is chosen.
- Whether `PLANNING_ELIGIBILITY` needs a new value for a "constraint,
  never a target" object like §1.4, or whether `fixed` already suffices —
  deferred to the dependent implementation requirement.

## Owner

Modelling / Platform engineering

## Approval date

2026-08-07
