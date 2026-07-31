# Curve authority gap analysis

Status: analysis supporting `docs/approved_requirements/REQ-CURVE-001.md` (draft). This
document does not itself approve an implementation; it is the evidence base the human
reviewer uses to approve or amend REQ-CURVE-001.

Reviewed at `main` commit `877add6cac7016ae285980936207643a3bb3de48` (PR #93 merged; no open
pull requests at review time). The PR 93A draft received five review findings after its merge
(section "PR 93 review findings" below); PR 94A revises both this analysis and the draft
requirement to address them. Locked dependency versions (`pyproject.toml`):
`pymc==5.28.5`, `pymc-marketing==0.19.2` (Python 3.11) / `0.19.4` (Python 3.12),
`arviz==0.23.4`, `pandas>=2.0.0`.

No MMM equation, prior, likelihood, adstock, saturation, attribution, curve calculation, or
optimiser mathematical changes are proposed or made by this document or by PR 93A / PR 94A.

---

## PR 93 review findings and how PR 94A addresses them

The five findings below were posted by the automated reviewer on `papayasamosa/MMM-Guide#93`
after the PR was merged (`877add6`). They are reproduced here so the reader can verify that
PR 94A actually addresses each one; REQ-CURVE-001 remains `draft`.

1. **P1 — Require curve-publication approval for official status.** `OUTCOME_USES` includes
   `model_fit` and `technical_reporting` (diagnostic/fitting uses), so the draft's "eligible
   for at least one" definition let a curve approved only for model fitting count as
   official. **PR 94A:** official status now requires a current, matching outcome approval
   for `curve_publication`; every downstream use stays independently gated; `model_fit`/
   `technical_reporting` alone never create official status (REQ-CURVE-001, Definitions,
   Governance chain, Publication and use).
2. **P2 — Apply the model's approved inverse link.** The draft's universal `mu = exp(eta)`
   would force the wrong scale for any future non-log-link outcome model. **PR 94A:** the
   general rule is now the fitted model's approved inverse link; `exp(eta)` is stated as the
   current count-model family only, not a permanent cross-model invariant (Mathematical
   contract).
3. **P1 — Validate complete reference contexts before publication.**
   `CurveReferenceContext.__post_init__` accepts empty/partial mappings and
   `steady_state_outcome_response` silently substitutes `0.0`, so the class does not already
   satisfy the no-implicit-zero contract. **PR 94A:** the current-state claim is corrected,
   and a complete-coverage requirement is added (validate keys against fitted model
   metadata/parameter structure; every fitted promo/control/outcome-control/Fourier/market/
   other-channel input covered; explicit governed zeros only; missing keys fail closed; extra
   keys surfaced; fingerprints bind keys and values; acceptance tests for missing/extra/
   partial/explicit-zero contexts).
4. **P2 — Reuse the existing planning-support gate.** The draft claimed a
   `planning_eligible` flag was missing, but `canonical_curves.py` already writes
   `planning_support_eligible` and `planning_blocked_reason` on every draw and
   `test_missing_support_is_unknown_and_blocks_planning` verifies the behaviour. **PR 94A:**
   the draft no longer proposes a duplicate field; the actual gap (downstream enforcement by
   planning/optimisation consumers) is what the requirement now states.
5. **P1 — Revalidate mutable approvals when an artifact is used.** Self-contained
   fingerprints prove only historical internal consistency; they cannot detect later
   expiry/revocation/supersession. **PR 94A:** the requirement now separates historical
   artifact integrity (immutable creation-time snapshot) from current official-use
   authorization (revalidation against live governance at every official use), with a
   fail-closed use-time gate.

PR 94A also corrects defects found during re-review beyond the five threads: eta-share
component allocation is labelled a versioned reconciliation convention, not a unique causal
decomposition (Work package F); artifact status is separated from outcome-approval status
rather than reusing `legacy_unapproved` as an artifact label (Work package G); and
overstated current-state claims are corrected with explicit current-implemented-behaviour /
approved-invariant / draft-proposed-requirement / known-implementation-gap /
future-capability labels (Work package H).

---

## 1. Current systems

The repository contains two structurally disjoint curve systems. Neither file references the
other's primary types (`grep` for `curve_bank`/`CurveBankEntry` inside
`ancestry_mmm/core/canonical_curves.py` returns zero matches beyond the unrelated function
name `export_canonical_curve_bank`).

### 1.1 Entry-oriented parameter Curve Bank

- `ancestry_mmm/core/curve_bank.py` (565 lines). `CurveBankEntry` (L61-110) is one *curve*
  (market, channel, segment-or-overall) as a **fitted-parameter snapshot**: `decay_rate`,
  `hill_K`, `hill_S`, `beta`, `halo_strength` — four to five scalars (posterior means), not
  posterior draws, and no explicit schema-version field (versioning is implicit via the
  `legacy_format`/`legacy_approval` booleans).
- `.from_dict()` (L115-126) filters incoming JSON to `{f for f in cls.__dataclass_fields__}`
  and silently drops any unrecognized key:
  ```python
  known = {f for f in cls.__dataclass_fields__}
  return [cls(**{k: v for k, v in d.items() if k in known})]
  ```
- `_expand_legacy_entry()` (L129-203) upgrades pre-Phase-3a, one-JSON-per-run files. Missing
  numeric fields default to `0.0`/`{}`/`None` via `.get(...)`; the resulting entries are
  correctly labelled `curve_status = CURVE_STATUS_LEGACY` and `legacy_format = True`, and
  `approved_by` defaults to the sentinel string `"(unknown - pre-dates approval gate)"`
  (L151) — so legacy expansion does not silently claim official status, but it does fabricate
  `0.0` parameter values for missing fields rather than refusing to construct the entry.
- `make_entries()` (L229-377) requires a `ModelApproval` (positional) and calls
  `require_matching_approval()` (L274-282); for `model_type="market_specific"` it requires an
  `evidence_tiers` mapping. `approval_readiness`/`current_policy` are optional
  (`TYPE_CHECKING`-only imports, L44) — PR #87 (merged immediately before this review) closed
  the gap where `07_Results_Curve_Bank.py` omitted them at its call sites while
  `make_entries()` itself already accepted them.
- `save_entries()` writes one JSON file per entry; `load_all_entries()` (L433-445):
  ```python
  try:
      entries.extend(CurveBankEntry.from_dict(json.loads(path.read_text())))
  except (json.JSONDecodeError, KeyError, TypeError):
      continue
  ```
  **Malformed files are skipped silently** — no logging, no exception, no user-visible
  warning. The same pattern applies to `load_all_calibrations()` (L550-560).
- Generators: `core/predict.py::generate_channel_curve()` (L493-591) and
  `core/market_specific_predict.py::generate_market_channel_curve()` (L359-449) are both,
  per their own docstrings, **point estimates only (posterior means)** on a spend/model-input
  axis, with **no `reference_context` or counterfactual parameter at all** — the shared-model
  docstring states channels "don't interact in this model's linear predictor," so the curve
  intentionally omits any other-channel context.
- `core/uncertainty.py::sample_draw_indices()` (L65-83) and
  `generate_channel_curve_with_uncertainty()`/`generate_market_channel_curve_with_uncertainty()`
  (L146-223) are a genuinely draw-level *opt-in* path: they re-run the point-estimate
  generators once per sampled `(chain, draw)` and summarize the resulting distribution. The
  module docstring is explicit that this is "the exact same calculation, run more than once,"
  not a redesign of the underlying curve.
- `ancestry_mmm/pages/07_Results_Curve_Bank.py` (889 lines) imports `predict`,
  `market_specific_predict`, `uncertainty`, and `curve_bank` — **it does not import or call
  `canonical_curves.py` anywhere**. Chart titles are generic (`"{channel} Response Curve"`,
  `components/charts.py` L225); the only status vocabulary shown to users is `curve_status`
  (`Shared`/`Locally estimated`/`Partially pooled`/`Transferred estimate`/`Legacy`) — an
  evidence-tier label, not an official/exploratory flag. The curve *viewer* renders
  unconditionally regardless of model-approval status; only the *save-to-bank* action is
  gated on `approval_matches_current`.
- `ancestry_mmm/components/charts.py` does import from `.canonical_curves` (L58), so at least
  one chart-rendering code path is wired to the canonical module, but page 07 does not invoke
  that path.

### 1.2 Canonical posterior curve system

- `ancestry_mmm/core/canonical_curves.py` (2246 lines). `CurveReferenceContext` (L96-261) is
  a frozen dataclass carrying market, trend, Fourier seasonality, promotions, controls,
  outcome controls, other-channel media input, counterfactual value/axis type, context mode,
  and reference period, with `__post_init__` validation (L168-189: finite/non-negative
  checks, `mode`/`counterfactual_axis_type` enum checks). `.to_dict()` stamps
  `"schema_version": 2` (L202-223). **Completeness caveat (PR 94A correction):**
  `__post_init__` validates the values that are *present*; it does **not** verify that every
  fitted promotion, common-control, outcome-control, Fourier, market, and other-channel
  input is represented. Empty or partial mappings are accepted, and
  `core.predict.steady_state_outcome_response` (L425-488) silently substitutes defaults for
  missing keys (`trend→1.0`, `fourier→zeros`, `promo→0.0`, `controls→0.0`,
  `outcome_controls→0.0`), so the existence of `CurveReferenceContext` is not by itself
  complete reference-context coverage — the draft's "already covers" wording overstated the
  current state. PR 94A adds a separate completeness requirement (missing keys fail closed,
  explicit governed zeros only, extra keys surfaced).
- `_normalise_support()` (L312-460) type-checks `MediaInputSupport` vs `MonetarySpendSupport`
  per `curve_type` and raises `TypeError` on a mismatch. **Hill K is never used as observed
  support** (confirmed by exhaustive grep — `hill_K` is read only for saturation math).
  Missing support is never fabricated: required keys
  (`observed_spend_min`/`max`, `current_spend`) absent → `observed_support_status =
  SUPPORT_MISSING` and every derived numeric field is set to `np.nan` (L396-412), not a
  default number. A distinct "planning support" range (`planning_spend_min/max`) exists,
  defaulting to the observed range only when not separately supplied.
- `generate_canonical_curve_draws()` (L839-1793) computes, per sampled draw,
  `incremental_response = mu(selected media input, context) - mu(counterfactual media input,
  same context)` through the ordinary outcome-scale prediction functions
  (`_predict()`, L776-796, calling `steady_state_outcome_response[_market_specific]`), before
  any summarization — `aggregate_curve_draws()` (L1796-2008) and `summarize_curve_draws()`
  (L2139-2210, posterior mean/median/credible-interval via quantiles) are separate, later
  calls that consume the draws DataFrame as input, so draw-level calculation strictly
  precedes any summary by construction.
- **The central governance gap.** `generate_canonical_curve_draws(governance_mode="official")`
  (default) does **not** reference `ModelApproval`, `ThresholdPolicy`, `ApprovalReadiness`,
  or `DiagnosticsArtefact` anywhere in the file (exhaustive grep: zero matches). The only
  operational effect of `governance_mode` is this conditional block (L960-975):
  ```python
  if activity_rows and governance_mode == "official":
      ...
      if unapproved_curve_activities:
          raise ValueError(
              "Monetary curves are blocked in official mode without "
              "approved activity governance ..."
          )
  ```
  `activity_rows` is built from the `activity_definitions` keyword argument
  (L907-911) and is empty whenever that argument is omitted (its default is `None`). **The
  official-mode activity-governance gate is therefore bypassed simply by not passing
  `activity_definitions`** — confirmed by the repository's own tests:
  `test_model_input_curve_is_available_without_cost_economics` and
  `test_monetary_curve_maps_spend_and_stores_chain_rule_derivatives`
  (`ancestry_mmm/tests/test_canonical_curves.py`) both call the module's `_generate` test
  helper with the default `governance_mode="official"` and never pass `activity_definitions`,
  and both succeed. `activity_definitions_fingerprint` is only written into the draw rows
  when `activity_rows` is non-empty (L1456-1460), so an official curve generated without
  `activity_definitions` carries no forensic record that the check was skipped, beyond the
  field's absence. The only check that is *not* mode-dependent or bypassable by omission is
  the cost-mapping requirement (L944-959): every `(market, channel)` on a monetary curve must
  resolve to a valid, effective `MediaCostMapping`, in both `"official"` and `"exploratory"`
  modes identically.
- This exact gap is independently confirmed by the maintainer's own description of PR #87
  (`papayasamosa/MMM-Guide#87`, merged 2026-07-30, immediately before this review), which
  states verbatim: *"`core.canonical_curves.py`'s separate `governance_mode="official"` gate
  (activity/cost-mapping only, no `ModelApproval` binding at all) is a larger, more ambiguous
  redesign question and is left untouched — noted as a remaining limitation, not addressed
  here."*
- `export_canonical_curve_bank()` (L2213-2246) writes `canonical_curve_draws.parquet`,
  `canonical_curve_summaries.parquet`, and a `canonical_curve_schema.json` stamped
  `"version": "G2A.2-1"` (a module/schema-level string, not a per-row version). **There is no
  round-trip import function anywhere in this file** (grep for `import_canonical`/`def
  .*import` returns nothing) — the module is currently write-only, so there is no code path
  today that answers "are unknown fields preserved on import" or "what happens on a malformed
  file."
- Currency/FX (`_currency_metadata()`, L732-773): for multi-market curves, an ISO local
  currency per market, an ISO reporting currency, and a non-empty `fx_as_of_date` are all
  required (raises otherwise); the resolved rate, source, and as-of date are persisted into
  every draw row.
- Component economics (`ComponentCostAllocation`, L285-305) are suppressed
  (`ECONOMICS_COMPONENT_COST_UNALLOCATED`) unless an explicit, sum-to-one cost allocation is
  supplied; channel spend is counted once, and allocated component costs are a fraction of
  that same channel-level spend, never double-counted.
- `docs/canonical_curves.md` (L3-4) states: *"`core.canonical_curves` is the non-UI source of
  truth for posterior curves, economics, governance views, reconciliation, and curve
  exports."* This claim is accurate as far as the mathematical/economic contract goes, and the
  document correctly never claims the UI has adopted it. But the document says nothing about
  `governance_mode`, `"official"` vs `"exploratory"`, or activity-definition approval gating
  at all — the mechanism at L960-975 (added by commit `a81058f`, "Add activity-approval hard
  gates and fingerprint into model identity") is undocumented there, so a reader has no way to
  learn from the doc that "official" mode's one governance check is skippable by omission.

---

## 2. Semantic differences

| Axis | Entry-oriented Curve Bank / `predict.py` generators | Canonical posterior system |
|---|---|---|
| Parameter snapshot vs evaluated curve | `CurveBankEntry` stores 4-5 fitted scalars (`decay_rate`, `hill_K`, `hill_S`, `beta`) | `generate_canonical_curve_draws` stores one evaluated `incremental_response` row per posterior draw × spend point × market × channel × component |
| Model-input axis vs monetary axis | `input_type` field distinguishes `"spend"`/`"media_unit"`, but the underlying curve generators (`generate_channel_curve`) do not enforce unit provenance beyond the caller's own bookkeeping | `curve_type` (`"model_input"`/`"monetary"`) is enforced structurally: `_normalise_support` raises `TypeError` on a mismatched support object, and monetary curves require a resolved `MediaCostMapping` |
| Segment/outcome curve vs channel-total curve | One entry per `segment_or_overall`; an "Overall" row sums `beta` across segments (valid because response is linear in `beta`) | Component rows (`component_type`) are an eta-share decomposition of the channel-total `incremental_response`, reconciled by construction |
| Component decomposition vs channel economics | Not distinguished — `beta` summation is the only decomposition mechanism | Explicit: component rows require `component_cost_allocation` before CPA/ROI; channel-total economics via `_economic_values` are independent of component allocation |
| Steady-state vs sequential | Both systems are steady-state only. `generate_canonical_curve_draws` stamps every row `"curve_method": "steady_state"` (L1396) unconditionally — there is no sequential/dynamic mode in either system today | (same) |
| Representative-context curve vs historical attribution | Neither `generate_channel_curve` nor `generate_market_channel_curve` takes a reference-context argument at all | `CurveReferenceContext` is explicit and required; `docs/canonical_curves.md` (L117-121) explicitly requires historical-attribution comparisons to use the same market/input/context/counterfactual/governance assumptions rather than being conflated with the curve |
| Exploratory view vs official artifact | No structural distinction anywhere — `curve_status` is an evidence-tier label (`Shared`/`Locally estimated`/etc.), not an official/exploratory flag; the viewer renders unconditionally regardless of approval | `governance_mode` is a string kwarg (`"official"`/`"exploratory"`) with **no structural type difference in the returned DataFrame** — both modes return the same schema; only one conditional check differs |
| Point estimate vs posterior-draw artifact | `generate_channel_curve`/`generate_market_channel_curve`/`CurveBankEntry` are point-estimate only by design (draws are an opt-in re-run via `core/uncertainty.py`, not the stored artifact) | Draw-level by construction; summarization is a separate, later step |

---

## 3. Governance differences

| Evidence element | Entry-oriented Curve Bank (`make_entries`) | Canonical (`generate_canonical_curve_draws`) |
|---|---|---|
| `ModelIdentity` | Not referenced directly; implied via fingerprints on `CurveBankEntry` (`data_fingerprint`, `model_spec_fingerprint`, `posterior_fingerprint`) | Not referenced anywhere in `canonical_curves.py` (zero grep matches) |
| `ModelApproval` | **Required** (positional arg); `require_matching_approval()` enforced | Not referenced |
| `ThresholdPolicy` | Optional (`current_policy`) | Not referenced |
| `ApprovalReadiness` | Optional (`approval_readiness`) | Not referenced |
| `DiagnosticsArtefact` | Not referenced directly by `curve_bank.py` | Not referenced |
| Outcome definition + approval | Handled upstream by `outcome_approval.py`'s `curve_publication` use, not inside `curve_bank.py` itself | Not referenced inside `canonical_curves.py` |
| Activity definitions/approval | Not referenced | **Conditionally required** — only when `activity_definitions` is explicitly supplied for a monetary curve in official mode; silently skipped if omitted |
| Pathway governance | `_pathway_weight()`/`_HasPathwayStrength` consulted by the underlying `generate_channel_curve`/`generate_market_channel_curve` | Consulted transitively through the same `steady_state_outcome_response[_market_specific]` prediction functions |
| Reference context | Not present at all | Required, validated (`CurveReferenceContext.__post_init__`) |
| Counterfactual | Not present at all | Required (`counterfactual_value`/`counterfactual_axis_type`, defaulted but always present and persisted) |
| Observed support | Not present | Typed, validated, never fabricated; missing → `NaN` + `SUPPORT_MISSING` status |
| Planning support | Not present | Present as a distinct optional range; every draw also carries `planning_support_eligible` (true only when observed support is available) and `planning_blocked_reason` (L1723-1726), but **no downstream planning/optimisation consumer reads them yet** — enforcement is the actual gap |
| Media-input specification | `input_type`/`unit_type` fields exist but are not independently validated against `MediaInputSpec` | `MediaInputSpec`/`MediaInputSupport` typed and validated |
| Cost mapping | Not referenced by `curve_bank.py` (handled separately for media-unit entries via `core.media_units`) | **Required unconditionally** for monetary curves, in both governance modes |
| Currency/FX | `currency`/`cost_per_unit` fields exist on `CurveBankEntry` but are not independently validated | **Required** for multi-market monetary curves (ISO codes, FX as-of date, resolvable rate) |
| Planning semantics | Not present | Not present (deferred to the governed future-assumptions work, PR 96A/96B per the roadmap) |
| Uncertainty | Not on the stored entry; available only via the separate `core/uncertainty.py` opt-in re-run | Draw-level by construction |
| Extrapolation status | Not present | Present via support status (`is_extrapolated`, per `docs/canonical_curves.md` L91) |

---

## 4. Upstream alignment

Context7 MCP was used, scoped to `/pymc-labs/pymc-marketing`. **Version caveat:** Context7's
resolver returned documentation snippets without a version-pinned corpus matching this
repository's locked versions (`pymc-marketing==0.19.2`/`0.19.4`); the snippets below are the
best available through Context7 and should be treated as directionally representative of the
0.18-0.19 API surface, not as a version-exact verification. This is disclosed per the MCP
fallback protocol rather than claimed as exact-version-verified.

| Repository | Version/commit consulted | Module/function | Example/test consulted | What is supported upstream | What remains Ancestry-specific |
|---|---|---|---|---|---|
| `pymc-labs/pymc-marketing` | Context7-served docs, unpinned (repo locks 0.19.2/0.19.4) | `mmm.saturation.sample_curve` / `mmm.plot.saturation_curves` | `skills/mmm-modeling/references/media_deep_dive.md` | Posterior-draw saturation curves, sampled from `mmm.idata.posterior`, with an `original_scale` toggle | No persisted governed artifact, no `ModelApproval`/outcome-approval binding, no reference-context object |
| `pymc-labs/pymc-marketing` | (same) | `mmm.plot.saturation_scatterplot` | `docs/source/notebooks/mmm/mmm_quickstart.ipynb` | Per-channel direct/marginal contribution vs. spend, at observed time points | No explicit counterfactual axis parameter — the reference is simply the historical data points themselves |
| `pymc-labs/pymc-marketing` | (same) | `mmm.incrementality.contribution_over_spend` | `skills/mmm-modeling/SKILL.md` | Incremental ROAS "accounts for adstock carryover" | No cost-mapping registry, no currency/FX layer, no multi-outcome pathway concept |
| `pymc-labs/pymc-marketing` | (same) | `mmm.sensitivity.run_sweep` / `mmm.plot.sensitivity_analysis` | `skills/mmm-modeling/SKILL.md`; `docs/source/notebooks/mmm/mmm_case_study.ipynb` | Relative sweeps of channel input around the channel's own historical total, posterior-draw HDI bands | The "reference" is always the channel's own historical total input, not an analyst-specified, persisted `CurveReferenceContext` with other-channel assumptions, trend/seasonality/promo/control values, and an explicit counterfactual |
| `pymc-labs/pymc-marketing` | (same) | `add_original_scale_contribution_variable` / `channel_contribution_original_scale` | `docs/source/notebooks/mmm/mmm_roas_parametrization.ipynb` | Outcome-scale (not log-link) channel contributions via inverse-transform of the target scaler | This repository's own `mu = exp(eta)` outcome-scale contract and `CurveReferenceContext` counterfactual mechanism are additional, Ancestry-specific layers on top |

**Do not claim upstream support for Ancestry-specific multi-outcome, pathway-governed,
monetary, or approval-chain behaviour.** None of the upstream APIs surveyed have any concept
of `ModelApproval`, `ThresholdPolicy`, `ApprovalReadiness`, `DiagnosticsArtefact`, outcome
definitions, activity definitions, cost-mapping registries, or an "official" vs "exploratory"
governance mode — these are entirely repository-specific and must continue to be treated as
such in REQ-CURVE-001, not attributed to or excused by upstream precedent. Upstream's
`sample_curve`/`saturation_scatterplot`/`sensitivity_analysis` confirm that draw-level,
posterior-based curve construction is itself a normal, well-supported pattern in
`pymc-marketing` 0.18-0.19 — which supports treating `canonical_curves.py`'s draw-level
design (not `curve_bank.py`'s point-estimate design) as the mathematically better-aligned
starting point, independent of the governance gap analyzed above.

---

## 5. Options

### Option A — `core.canonical_curves` as the authoritative calculation, plus a new application-service governance layer

Make `generate_canonical_curve_draws`/`aggregate_curve_draws`/`summarize_curve_draws` the
sole calculation path for new official curves, and introduce a new
`ancestry_mmm/application/` service (parallel to the existing `diagnostics_service.py`,
`validation_service.py`, `project_service.py`) that:
- requires (not merely accepts) `ModelIdentity`, `ModelApproval`, `ThresholdPolicy`,
  `ApprovalReadiness`, `DiagnosticsArtefact`, an approved `OutcomeApproval` for
  `curve_publication`, and — unconditionally, not skippable by omission — approved
  `ActivityDefinition`s for every monetary (market, channel);
- calls `generate_canonical_curve_draws` only after that chain is satisfied;
- persists the resulting artifact with an explicit, versioned schema (not the current
  write-only Parquet + module-string-version export).

| Criterion | Assessment |
|---|---|
| Mathematical correctness | Strong — inherits the already-correct draw-level, context/counterfactual contract |
| Outcome-scale interpretation | Strong — already enforced by `_predict`/`_economic_values` |
| Governance completeness | Strong, but only *after* the follow-on work (PR 95A/95B) closes the current gap — not automatic from Option A alone |
| Auditability | Strong — fingerprints (`activity_definitions_fingerprint`, `monetary_governance_fingerprint`) already exist and can be made unconditional |
| Backward compatibility | Requires an explicit legacy-migration story (Section 7) since `CurveBankEntry` records must not silently become "official" under the new contract |
| Schema migration | New work required — no row-level schema version exists across the whole export today, and no import/round-trip path exists at all |
| UI migration | Largest lift — `07_Results_Curve_Bank.py` currently uses neither `canonical_curves` nor an application service; a full UI migration is required (PR 95E) |
| Future sequential planning | Compatible — `CurveReferenceContext` already has a `mode` field; sequential is additive, not a redesign |
| Multi-market currency | Strong — already enforced | 
| Media-input vs monetary units | Strong — already enforced via `curve_type`/`MediaInputSpec` |
| Posterior uncertainty | Strong — draw-level by construction |
| Maintainability | One calculation path going forward; the entry-oriented store becomes explicitly legacy, reducing long-term duplication |

### Option B — Keep `CurveBankEntry` as a fitted-parameter registry; add a distinct canonical evaluated-curve artifact for official use

Leave `curve_bank.py` exactly as it is (a fitted-parameter snapshot registry, useful for
calibration tracking, evidence-tier display, and the current UI), and introduce a *new*,
separately named official artifact type built on `canonical_curves.py`'s calculation, without
retrofitting or renaming `CurveBankEntry`.

| Criterion | Assessment |
|---|---|
| Mathematical correctness | Same strength as Option A (same calculation source) |
| Outcome-scale interpretation | Same as Option A |
| Governance completeness | Same as Option A (governance work is identical; it lives in the new artifact/service either way) |
| Auditability | Slightly clearer than Option A — no risk of conflating "parameter snapshot" and "evaluated official curve" under one class name, since they remain permanently distinct types |
| Backward compatibility | Best of the three — zero risk to existing `CurveBankEntry` consumers (calibration tracking, evidence-tier UI) since nothing about that class changes |
| Schema migration | Same new-schema work as Option A, but scoped to a brand-new type rather than touching `CurveBankEntry`'s existing (already-deployed) schema |
| UI migration | Same lift as Option A — the UI still must add a new official-curve view; existing curve-viewer/evidence-tier functionality is undisturbed |
| Future sequential planning | Same as Option A |
| Multi-market currency | Same as Option A |
| Media-input vs monetary units | Same as Option A |
| Posterior uncertainty | Same as Option A |
| Maintainability | Two types remain, but with a clean, permanent, non-overlapping purpose split (calibration/evidence-tier registry vs. governed official artifact) rather than a "legacy vs. current" split that erodes over time |

### Option C — Extend `CurveBankEntry` into the full official artifact; retire canonical export

Add posterior-draw storage, reference-context, counterfactual, support, cost/currency, and
the full governance chain directly onto `CurveBankEntry`/`curve_bank.py`, and stop using
`canonical_curves.py`'s export path.

| Criterion | Assessment |
|---|---|
| Mathematical correctness | Requires re-deriving `canonical_curves.py`'s already-correct, already-tested draw-level/counterfactual/reconciliation logic inside `curve_bank.py`, or importing it there — duplicative either way |
| Outcome-scale interpretation | Same target contract, but built from scratch inside a module whose current generators (`generate_channel_curve`) are explicitly point-estimate-only by design |
| Governance completeness | Same target as A/B |
| Auditability | Weakest — conflates "one JSON file per fitted-parameter snapshot" (`curve_bank.py`'s current, deployed persistence model) with "one governed, multi-thousand-row posterior-draw artifact," which is a much larger object with different query/versioning needs |
| Backward compatibility | Directly touches the one class (`CurveBankEntry`) every existing UI page, calibration record, and legacy-import path already depends on — highest regression risk of the three options |
| Schema migration | Largest — `CurveBankEntry`'s current one-JSON-per-curve file format was not designed for draw-level data (a single curve's draws can be thousands of rows; `save_entries()`'s current one-file-per-entry JSON model does not fit this) |
| UI migration | Same lift as A/B for the new official view, plus risk to the *existing* curve-viewer/evidence-tier UI since it shares the class being changed |
| Future sequential planning | Compatible in principle, but built without `canonical_curves.py`'s existing `mode`/reference-period scaffolding |
| Multi-market currency | Would need to be built from scratch inside `curve_bank.py` — `canonical_curves.py`'s already-tested `_currency_metadata` logic would be discarded per this option's own premise ("retire canonical export") |
| Media-input vs monetary units | Same re-derivation cost |
| Posterior uncertainty | Same re-derivation cost; `core/uncertainty.py`'s existing opt-in re-run pattern is a materially different design (re-run point estimate N times) from `canonical_curves.py`'s native per-draw generation, and reconciling the two inside one module is nontrivial |
| Maintainability | Retiring already-built, already-tested code (`canonical_curves.py`, ~2246 lines with its own test file) to duplicate its functionality elsewhere is the weakest maintainability case of the three |

Option C is not recommended: it is evaluated fully above (not selected merely for having the
fewest superficial code changes, since it in fact requires the *most* net new/duplicated
work — retiring ~2246 already-tested lines and their draw-level, context, counterfactual,
currency, and reconciliation logic, then rebuilding equivalent behavior inside a module whose
current generators are point-estimate-only by design).

---

## 6. Recommendation

**Option B** — keep `CurveBankEntry` permanently scoped to what it already is (a fitted
Hill/decay/beta parameter snapshot registry, used for calibration tracking and evidence-tier
display), and introduce a new, distinctly named, separately schemed official evaluated-curve
artifact built on `core.canonical_curves`'s existing draw-level calculation, produced only
through a new application-service governance layer.

- **Calculation source of truth:** `ancestry_mmm/core/canonical_curves.py`
  (`generate_canonical_curve_draws` → `aggregate_curve_draws`/`summarize_curve_draws`). No
  change to its mathematical contract is proposed here.
- **Application-service boundary:** a new module (naming TBD in PR 95A, e.g.
  `ancestry_mmm/application/curve_service.py`, mirroring the existing
  `diagnostics_service.py`/`validation_service.py`/`project_service.py` pattern) that
  *requires* — not merely accepts — the full governance chain listed in Section 3
  (including a current `curve_publication` outcome approval and complete reference
  contexts) before calling `generate_canonical_curve_draws`, and that makes the current
  activity-approval check unconditional for official monetary curves rather than skippable
  by omitting `activity_definitions`.
- **Persisted official artifact:** a new, versioned type (not `CurveBankEntry`), replacing or
  extending `export_canonical_curve_bank`'s current write-only Parquet+JSON export with a
  format that has a real row/artifact-level schema version, round-trip import, and audited
  (not silently-skipped) malformed-file handling — following the same "fail closed" pattern
  the repository already uses in
  `ancestry_mmm/application/validation_service.py::MalformedArtefactEvidenceError` (L47-55).
- **Legacy parameter snapshots:** `CurveBankEntry`/`curve_bank.py` remain exactly as they are
  today, permanently — not deprecated, not retrofitted — since they serve a genuinely
  different purpose (calibration-record tracking, evidence-tier UI) that the new artifact
  does not replace.
- **Exploratory views:** `governance_mode="exploratory"` continues to exist as a
  structurally distinct, non-persistable (or distinctly-typed) result — not the same
  DataFrame schema silently relabelled, so a UI or downstream consumer cannot mistake one for
  the other by inspecting only a string field.
- **Publication eligibility:** official status requires a current, matching outcome approval
  for `curve_publication` (PR 94A correction for review finding 1); every downstream use
  (`planning`, `optimisation`, `headline_reporting`, `technical_reporting`,
  `external_distribution`) is independently gated on its own current, matching approval.
  Reuses the existing `OUTCOME_USES` vocabulary already defined in
  `ancestry_mmm/core/outcome_approval.py` rather than inventing a parallel vocabulary.
- **Planning-support enforcement:** the official service and every planning/optimisation
  consumer must enforce the existing `planning_support_eligible` value and a non-empty
  `planning_blocked_reason` when ineligible; no duplicate `planning_eligible` field is
  introduced (PR 94A correction for review finding 4).
- **Artifact status is separate from outcome-approval status:** the new artifact keeps its
  own lifecycle vocabulary (format/migration status, historical evidence integrity, current
  authorization status, requested-use eligibility) and does not reuse `legacy_unapproved` as
  an artifact label (PR 94A correction, Work package G).

Option B is chosen over Option A specifically because Option A's wording ("make
`canonical_curves` authoritative... introduce an application service") does not by itself
settle whether `CurveBankEntry` is retired, frozen, or migrated — leaving that ambiguous
invites exactly the kind of "is this fitted-parameter snapshot also an official curve now?"
confusion the brief and `AGENTS.md` (L172-212: curves must store reference context,
counterfactual, model-input axis, monetary axis, support provenance, uncertainty,
extrapolation status) are both trying to prevent. Option B makes the split explicit and
permanent as part of the recommendation itself, at no extra implementation cost over Option A
(the same new service and new artifact schema are built either way).

---

## 7. Migration sequence

This document does not implement any of the following; it records the staged sequence for
human review, matching the follow-on PRs named in the task brief after PR 94A (the corrected
plan supersedes the earlier PR 93B-93G numbering; PR 93B was never merged to `main`).

0. **PR 94A (this PR)** — Correct the draft requirement and this analysis; the requirement
   stays `draft`. No code, schema, persistence, or UI change.
1. **PR 94B** — After the user explicitly approves REQ-CURVE-001 and its human-decided
   options, approve the requirement (change `status` to `approved_for_implementation`) and
   register the implementation acceptance tests named in the requirement's Testing
   requirements section.
2. **PR 95A** — Define the new official-artifact schema (versioned, JSON-safe metadata,
   portable draw/summary tables, deterministic fingerprints, round-trip import, migration
   hooks) and the new `CurveService` application boundary. No behavior change to any existing
   generator yet.
3. **PR 95B** — Route `generate_canonical_curve_draws` calls for official curves exclusively
   through the service; require the full governance chain including a current `curve_publication`
   outcome approval; make the activity-approval check unconditional (not omission-skippable)
   for official monetary curves; require complete reference contexts (missing keys fail
   closed, explicit governed zeros only); enforce `planning_support_eligible` downstream.
4. **PR 95C** — Add current-use revalidation and artifact staleness checks: at every official
   use, revalidate against current threshold policy, current outcome approval for the
   requested use, current activity approval, staleness, and revocation/expiry (Historical
   artifact integrity vs. current official-use authorization).
5. **PR 95D** — Add canonical artifact import, migration, and malformed-file audit (no
   silent `continue`), preserving legacy bundle loadability; keep artifact status separate
   from outcome-approval status per the human-approved vocabulary from Work package G.
6. **PR 95E** — Migrate `07_Results_Curve_Bank.py` (or a new page) to render the new official
   artifact for governed views, while the existing point-estimate `generate_channel_curve`/
   `generate_market_channel_curve` viewer remains available and explicitly labelled
   exploratory/legacy.
7. **PR 95F** — Retain legacy parameter snapshots (`CurveBankEntry`) but remove any
   official-curve labelling from them; they remain loadable and usable for calibration
   tracking and evidence-tier display, never presented as current official artifacts.
8. **PR 96A/96B** — Draft and implement governed future-assumption requirements (including
   sequential curves) and scenario persistence.
9. **PR 97A** — Hardening: strengthen coverage, warnings, typing, browser E2E, and Bayesian
   recovery.

Downstream planning/optimisation/forecasting work (capacity-constrained Search, Chronos-2,
full-funnel mediator simulation, real UK/AU/CA data) is explicitly out of scope until this
governance and persistence sequence is approved and merged, per the task brief.
