# REQ-LATENT-001: Latent-State Scale and Location Identification

## PRD source

Ancestry MMM PRD Part 6 v1.6 (intro bullet 3, §16.1, §16.5, §30.1, §30.3, §37
`MD-021`, §38 AC-09), Part 7 v1.5 (§0.15 intro bullet 5, §9.1, §20.7, §39
blocking condition #6, §48 `VL-026`), and Part 10 v1.6 (`FCH-02`, §17.7
"Latent-state identification", §44, §47 `UX-028`) — reconciled by Work
Package 0 of `Media-Mix-Lab: Coding LLM Next Steps Post PR #267`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief cited
above (2026-08-17). Candidate A latent branded-search demand
(`REQ-SEARCH-002`) is the first concrete integration target for this record,
per the brief's own instruction; this record does not itself approve a
specific identification strategy for that state.

No module in this repository currently declares or validates a scale/
location identification strategy for a fitted latent state. `core.
search_capacity`'s latent demand state has no recorded identifying
constraint.

## Capability status

Core diagnostic implemented (Work Package 3, second record, 2026-08-17):
`ancestry_mmm/core/latent_state_identification.py` provides a model-
agnostic identification-declaration contract and empirical stability
check. `LatentStateIdentificationDeclaration` stores the identifying
strategy for one latent state explicitly (one of the five kinds listed
in Requirement 1; a required, non-empty `description`; an optional
`anchor_reference`) — satisfying Requirement 2's "must be stored ...
not left implicit in code." `assess_latent_state_identification`
resolves a closed, four-value status per latent state (`identified`;
`review_required`; `not_identified`; `unsupported_by_current_checker`):
no declaration at all is `not_identified` outright (Requirement 1
directly unmet); a declaration with no supplied posterior draws is
`review_required` (declared but not yet empirically checked under
sampling, per Requirement 4); fewer than two supplied chains is
`unsupported_by_current_checker`; two or more chains are compared by
each chain's median of a caller-supplied representative scalar, and
disagreement in sign across chains — a structural indeterminacy, not a
graded threshold — is `not_identified` with `sign_flip_detected=True`
(Requirement 4's "posterior sampling does not reveal unresolved scale
or sign indeterminacy"). `scale_drift_ratio` is always reported as
descriptive evidence only, mirroring `core.structural_stability.
ParameterFoldComparison.point_range`'s "report movement, never a
verdict" pattern, since no scale-drift materiality threshold has been
approved. `is_eligible_for_official_use` implements Requirement 5's
fail-closed use-eligibility gate: only `identified` is eligible: every
other status, including `review_required`, fails closed. Every result
carries `LATENT_STATE_IDENTIFICATION_DISCLAIMER` and never exposes a
bare boolean. This is a standalone module/dataclass family, never
collapsed into `EstimandIdentificationResult` or
`StructuralStabilityArtefact` (Requirement 6).

This module does not fit or re-fit a model — the caller supplies the
declaration and, optionally, per-chain posterior draws, mirroring
`core.structural_stability`'s established "the caller supplies the
fold-local computation" pattern. It does not modify `core.
search_capacity` and does not assert or imply any specific identifying
anchor for Candidate A's `latent_branded_search_demand` — that
substantive statistical choice (`MD-021`) remains an explicitly
unresolved decision, per this reconciliation record's own "Unresolved
decisions" section and the PRD-authority instruction governing this
program (do not implement directly from PRD prose without an approved
requirement or decision package; do not guess an unresolved statistical
decision).

`DiagnosticsArtefact`/Diagnostics-page wiring now complete (Work Package 2
of `Media-Mix-Lab: Coding LLM Next Steps After PR #286`, canonical
Diagnostics evidence integration, 2026-08-18): schema v8 adds the
`latent_state_identification` section, computed inline in
`DiagnosticsService.evaluate()`. Dispatch mirrors `search_capacity`'s own
`meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE` check: an ordinary
fit with no declared latent state is `not_applicable`; a Candidate A fit
always assesses `candidate_a_latent_branded_search_demand` — with no
supplied declaration this correctly resolves `not_identified`
(Requirement 1 unmet, the fail-closed contract, never a fabricated pass),
and a declaration with no chain draws resolves `review_required`. Any
caller-supplied `LatentStateIdentificationDeclaration`s are assessed
alongside it. `pages/06_Diagnostics.py` reports this section separately
from every other evidence dimension. This wiring does not assert or
declare any specific identifying anchor for Candidate A's latent demand —
`MD-021` remains the unresolved statistical decision it always was.

Not yet implemented: Requirement 3 (extending `core.graph_model_
compiler`'s blocking-error contract for unresolved latent-state
identification), and full synthetic-recovery validation and decision-
instability detection for Requirement 4's remaining two sub-items (both
require a real fit/re-fit pipeline this module does not run) — deferred
as separate integration follow-ups.

## Requirement

### 1. Every fitted latent causal state needs an identifying strategy

Every fitted latent mediator, latent demand pool, or other latent state that
enters a causal pathway (including Candidate A's latent branded-search
demand, and any future latent baseline state) must declare how its scale and
orientation are identified, using one of:

- fixing one measurement or structural loading;
- anchoring the latent state to an observed quantity with a defined unit;
- constraining a reference variance or scale;
- a validated measurement model with an identified loading structure;
- another approved identifying constraint with equivalent statistical
  effect.

### 2. The identifying choice is substantive, not cosmetic

The identifying choice determines what one unit of the latent state means.
It must be stored in the model specification and effect metadata, not left
implicit in code. Prior regularisation alone must not be described as
resolving structural non-identification.

### 3. Compiler-level rejection of unresolved rescaling/sign indeterminacy

The model compiler must reject a latent structure that remains invariant
under an arbitrary rescaling or sign reversal that could be offset by
another free parameter, unless the intended posterior quantity is otherwise
identified. This extends `core.graph_model_compiler`'s blocking-error
contract (`REQ-GRAPH-001` §7): a fitted latent mediator or latent demand
state with no valid scale-identification strategy is a compiler-level
blocking error, not a warning.

### 4. Validation must confirm the anchor holds under sampling

Validation must confirm: the anchor or constraint is present in the compiled
model; the resulting scale is interpretable for the requested estimand;
posterior sampling does not reveal unresolved scale or sign indeterminacy;
synthetic recovery succeeds for custom/advanced latent structures; changes to
the identification choice do not create unexplained decision instability.

### 5. Reporting and use-eligibility gate

A latent mediator or latent demand state without an approved identifying
scale or anchor must remain visibly unsuitable for official causal
reporting, curve publication, planning, or optimisation for the affected
pathway — this is a fail-closed gate, consistent with the existing Search
fail-closed pattern (`core.predict.predict_mu`/`core.attribution.
compute_shapley_contributions` already fail closed for an unwired Candidate
A pathway under `REQ-SEARCH-002`; this record extends the same fail-closed
principle to identification specifically, not only to wiring).

### 6. Separate evidence dimension

Latent-state identification status must be reported separately from
estimand-specific graphical identification (`REQ-IDENT-001`), predictive
validation, and structural stability — never collapsed into one
undifferentiated status.

## Explicitly excluded (decision-required, not approved by this record)

- for each specific approved latent mediator or latent demand state
  (including Candidate A), the actual substantive scale anchor, measurement
  model, or identifying constraint, and the business interpretation of one
  unit of that state (Part 6 §37 `MD-021`);
- the accepted general-purpose identification-strategy taxonomy where it
  extends beyond the five listed in Requirement 1 (Part 7 §48 `VL-026`);
- business/technical labels for identification status (Part 10 §47
  `UX-028`).

## Affected modules

- `ancestry_mmm/core/latent_state_identification.py` (new —
  `LatentStateIdentificationDeclaration`, `LatentStateIdentificationResult`,
  `assess_latent_state_identification`, `is_eligible_for_official_use`)
- `ancestry_mmm/core/search_capacity.py` (not yet touched — Candidate A's
  latent demand state remains the first concrete integration target, but
  its actual identifying anchor is a separate, unresolved decision)
- `ancestry_mmm/core/graph_model_compiler.py` (not yet touched —
  Requirement 3's compiler-blocking extension is deferred)
- `ancestry_mmm/core/structural_stability.py` (read-only precedent for
  this record's "caller supplies the computation" and "report movement,
  never a verdict" patterns — no shared code, no coupling)
- `ancestry_mmm/pages/14_Causal_Graph.py` (not yet wired — deferred)
- `ancestry_mmm/application/diagnostics_service.py` (Work Package 2 —
  `DiagnosticsArtefact` schema v8 `latent_state_identification` section,
  computed inline in `evaluate()`, `CANDIDATE_A_LATENT_DEMAND_STATE_ID`)
- `ancestry_mmm/pages/06_Diagnostics.py` (Work Package 2 — wired)
- `docs/approved_requirements/REQ-LATENT-001.md` (this record)
- `docs/approved_requirements/index.json` (updated)

## Required tests

- `ancestry_mmm/tests/test_latent_state_identification.py` (26 tests:
  declaration validation/round-trip; no declaration resolving
  `not_identified` regardless of supplied chain draws; a declaration
  with no chain draws resolving `review_required`; fewer than two
  chains resolving `unsupported_by_current_checker`; disagreeing signs
  across two and three chains resolving `not_identified` with
  `sign_flip_detected=True`, including a zero-median chain counting as
  a distinct sign; agreeing signs resolving `identified` with a
  descriptive `scale_drift_ratio`; caller-contract errors for a missing
  latent_state_id, a mismatched declaration latent_state_id, and an
  empty chain; the fail-closed use-eligibility gate for every status;
  and result validation/round-trip with and without a declaration)
- `ancestry_mmm/tests/test_diagnostics_artefact.py::TestEvaluateLatentStateIdentification`
  (Work Package 2 — ordinary fit not_applicable; Candidate A fit with no
  declaration not_identified; declaration with no chain draws
  review_required; round trip/fingerprint)
- `ancestry_mmm/tests/test_diagnostics_wp2_evidence_apptest.py::test_scorecard_reports_not_applicable_latent_state_and_experiment_sections`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

## Migration impact

Resolved (Work Package 2): `DiagnosticsArtefact` schema v7 → v8. An
artefact computed before schema v8 upgrades this section to `not_computed`
with an explicit "added in schema v8" message. No model-mathematics files
changed — `core.search_capacity`'s latent-demand construction still
declares no identification strategy; Requirement 3 against Candidate A
still requires that separate, unresolved change once implemented.

## Unresolved decisions

- Candidate A's actual identifying anchor/constraint (`MD-021`) — statistical
  modelling decision, not resolvable by this reconciliation record.
- Whether identification validation runs at fit time, as a separate
  Diagnostics check, or both — **partially resolved**: it now runs as a
  Diagnostics-page check (Work Package 2, see Capability status above);
  fit-time validation is not implemented.

## Owner

Modelling

## Approval date

2026-08-17
