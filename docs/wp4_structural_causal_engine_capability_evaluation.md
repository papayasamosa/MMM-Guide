# WP4 Structural-Causal Engine Capability Evaluation (decision support)

Status: capability-evaluation evidence only. No engine is selected,
enabled, or added by this package. No production code accompanies it.
This document performs the capability-matrix evaluation that
`docs/wp_structural_causal_engine_decision_package.md` (Work Package 0)
identified as candidate D1-A's own work ("run the
Work-Package-4-style capability-matrix evaluation ... before any adoption
decision"). It does not decide D1, D2, or D3 from that package; those
remain open under `MD-022`, `VL-028`, `VL-029`, `UX-031`, `UX-032`,
`UX-033`.

## Why this package exists

Work Package 4 of `Media-Mix-Lab: Coding LLM Next Steps After PR #291`
(2026-08-19) requires the structural-causal engine evaluation and
decision package. The governing records
(`REQ-SCENGINE-001`, `REQ-SCEFFECT-001`, `REQ-CAUSALROBUST-001`,
`REQ-SCCURVE-001`) approve target-state *contracts* only and explicitly
exclude engine selection. This package supplies the missing
evidence layer those records' "Explicitly excluded" sections point at:
a documented, source-cited capability matrix of the candidate engines
against the approved contracts, using the repository's own approved
capability vocabulary, so that the human decision owners of `MD-022`
etc. can review evidence rather than re-derive it.

All upstream facts below were retrieved from current official sources on
2026-08-19 (see "Sources" at the end). No capability is asserted from
memory, PRD prose alone, or the local PRD suite (which was excluded from
staging by the brief and remains untracked).

## Approved classification vocabulary

Root `AGENTS.md` ("Engine-capability boundary") requires every approved
model specification to record, per capability, whether it is:

- native to the selected engine
- implemented through a supported extension
- implemented through an external linked model
- a planning-layer approximation
- experimental
- not supported

This package uses exactly those six labels, scoped per dimension. The
primary production engine is PyMC (`REQ-ENGINE-001`, resolved, not
re-opened here). Candidate A's Search mediation/capacity engine
(`REQ-SEARCH-002`) is an explicitly selected external linked engine and
is not replaced by anything in this package (`REQ-SCEFFECT-001` §5,
`REQ-SCCURVE-001` §5).

## Evaluation dimensions

Derived mechanically from the four governing records:

- D1  Engine identity, maturity, licence, maintenance activity
- D2  Likelihood families (Gaussian, count with log link, etc.) —
     `REQ-SCEFFECT-001` §2
- D3  Hierarchical / random-effects support — `REQ-SCENGINE-001` §2
- D4  Temporal structures (carry-over, lags) and MMM transforms —
     `REQ-SCENGINE-001` §2
- D5  Observed-variable mediation as jointly estimated structural
     equations; direct/mediated/total decomposition —
     `REQ-SCEFFECT-001` §1/§4
- D6  Graphical identification surface — `REQ-IDENT-001`,
     `REQ-SCENGINE-001` §2
- D7  Posterior intervention on the outcome scale (g-computation style)
     with declared endogenous response — `REQ-SCEFFECT-001` §2/§3
- D8  DAG falsification — `REQ-CAUSALROBUST-001` §1
- D9  Placebo / permutation refutation — `REQ-CAUSALROBUST-001` §1
- D10 Unmeasured-confounding sensitivity — `REQ-CAUSALROBUST-001` §1
- D11 Dependency/runtime compatibility with the pinned primary stack
     (Python >=3.11,<3.13; `pymc==5.28.5`; `pytensor==2.38.3`;
     `numpy>=1.24`; `pymc-marketing==0.19.x`) —
     `REQ-SCENGINE-001` §4
- D12 Generated-spec versus authored-DSL risk (the approved graph must
     remain the sole structural authority; engine-native DSL must never
     become a second editable source) — `REQ-SCENGINE-001` §1
- D13 Persisted-artefact portability (readable without the optional
     runtime) — `REQ-SCENGINE-001` §6
- D14 Provenance fields achievable (engine id/version, runtime identity,
     graph structural fingerprint, generated-spec fingerprint) —
     `REQ-SCENGINE-001` §5
- D15 Ragged-coverage / multi-market patterns —
     `REQ-SCENGINE-001` §2 (capability resolution must cover
     "ragged-coverage pattern")
- D16 Observed-support / extrapolation signalling — `REQ-SCCURVE-001`
     §2 and `REQ-CURVE-001` support provenance

## Candidate engines evaluated

1. **PathMC** — `pymc-labs/pathmc`, PyPI `pathmc` 0.3.0. The PRD's own
   named candidate. PyMC-native Bayesian structural causal modelling.
2. **DoWhy** — `py-why/dowhy`, PyPI `dowhy` 0.14. PyWhy's causal
   inference framework (identification, estimation, refutation, GCMs).
3. **pgmpy** — `pgmpy/pgmpy`, PyPI `pgmpy` 1.1.2. Probabilistic
   graphical models library.
4. **No supplemental engine** — the existing primary PyMC compiler plus
   Candidate A (the "remains on the existing primary MMM / Candidate A
   path" fallback in `REQ-SCENGINE-001` §2). Included as the baseline
   against which a new dependency must justify itself.

## Capability matrix

Legend: N = native; E = supported extension; L = external linked model;
P = planning-layer approximation; X = experimental; U = not supported;
NV = not verified from current upstream documentation (open question,
does not imply support).

| Dimension | PathMC 0.3.0 | DoWhy 0.14 | pgmpy 1.1.2 | No supplemental engine |
| --- | --- | --- | --- | --- |
| D1 identity/maturity | Apache-2.0, PyMC Labs, status "beta", actively pushed 2026-08-17 | MIT, PyWhy, v0.14 (docs Nov 2025), actively maintained | MIT, NumFOCUS-affiliated, v1.1.2, maintained | n/a (already in repo) |
| D2 likelihood families | N — Gaussian, Bernoulli, Poisson, NegBinomial, StudentT (`families=` DSL) | N (GCM supports flexible models; classic estimators support linear/logistic/ML models) | N for discrete Bayesian networks; SEM linear Gaussian | N — primary engine's count model (log link) |
| D3 hierarchical/panel | N — `panel={"unit","time"}`, `pooling` random intercepts + random slopes | U (no native panel MMM hierarchy) | U | N — repo's market/segment hierarchy |
| D4 temporal/MMM transforms | N — `adstock()`, `logistic_saturation()`, custom `Transform`, `simulate_over="time"` | U | U | N — repo's adstock/Hill semantics |
| D5 mediation/decomposition | N — structural equations, labeled paths, `:=` indirect, `effect()` | N (path-specific via identification + estimators; GCM for mechanisms) | P — SEM module exists, no Bayesian uncertainty | L — Candidate A two-stage (authorised Search only) |
| D6 identification | N — `adjustment_sets()`, `is_identifiable()`, collider warnings | N — exhaustive identification algorithms (backdoor/IV/front-door) | N — do-calculus identification | P — repo's `estimand_identification` (REQ-IDENT-001) |
| D7 outcome-scale posterior intervention | N — `do()`, `ate()`, `cate()`, `prob()`, `comparisons()` (diff/ratio/lift) via g-computation, full posterior draws | P — GCM interventional samples; point/CI estimates by default, not full posterior MCMC | N (interventional distributions, frequentist) | L — primary posterior prediction + Candidate A counterfactuals |
| D8 DAG falsification | N — `test_implications()`, whole-graph permutation `falsify_graph()` | N — graph refutation tests | P — validation metrics exist | U (not implemented; WP3 records this) |
| D9 placebo/permutation refutation | NV — permutation-based *graph* falsification documented; treatment-severing placebo refutation not documented upstream | N — placebo treatment refuter is a first-class API | U | U |
| D10 confounding sensitivity | N — `sensitivity()` tipping-point analysis | N — placebo/common-cause/data-subset refuters + partial R2 | U | U |
| D11 runtime compatibility with pinned stack | U today — requires Python >=3.12, `pymc>=6,<7`, `pytensor>=3.1.1,<4`, `numpy>=2.0`; repo pins `pymc==5.28.5`, `pytensor==2.38.3`, `numpy>=1.24` | U in-process — `numpy>2.0` and `scipy` constraints conflict with pinned stack; no PyMC interop | U in-process — `numpy>=2.0`, no PyMC interop | N |
| D12 generated-spec architecture | N — spec is a plain string; upstream ships `dag_to_spec()` and `BuildModelFromDAG`, so spec can be *generated* (derived state) rather than authored | P — GCM graph objects are constructed programmatically from a DAG | P — SEM built programmatically | N |
| D13 artefact portability | N — outputs are ArviZ `InferenceData`/`DataTree`, PyMC objects; portable, not opaque runtime-specific formats | N — numpy/pandas artefacts | N — numpy/pandas artefacts | N |
| D14 provenance fields | N — engine id/version capturable; graph fingerprint and generated-spec fingerprint must be added by the adapter (contract work, not engine work) | N (same adapter work) | N (same adapter work) | L — `FHModelMeta` graph identity fields already exist |
| D15 ragged coverage | NV — panel mode documented for balanced panels; ragged/irregular multi-market coverage not documented | U | U | N — repo's ragged handling (REQ-STATE etc.) |
| D16 support/extrapolation signalling | N — `do()` warns when intervention values fall outside observed ranges | NV | U | N — repo's support/extrapolation status fields |

## Hard findings that bind any future adapter

### F1 — PathMC meets the runtime-isolation trigger today

`REQ-SCENGINE-001` §4 permits isolation "only where required ... justified
only by an actual demonstrated dependency ... need for the specific
engine". For PathMC the need is demonstrated and current: PathMC 0.3.0
requires `pymc>=6.0,<7` and `pytensor>=3.1.1,<4`, while the repository
pins `pymc==5.28.5` and `pytensor==2.38.3` (primary-engine pins are a
change-controlled boundary — `docs/pymc_marketing_alignment.md`). PathMC
therefore cannot be co-installed in the primary runtime without a
major primary-engine upgrade; any real evaluation run must use an
isolated worker/venv (per §4) or must first obtain a separately approved
primary-stack upgrade. DoWhy and pgmpy have the inverse problem: they do
not conflict as sharply with PyMC but they are not Bayesian MMM engines
at all (no hierarchical panel adstock/saturation machinery), so they
cannot satisfy the estimation half of `REQ-SCEFFECT-001` without a
custom estimation layer.

### F2 — Generated-spec architecture is feasible; it must be the only allowed path

PathMC's model surface is a formula string (`~`, `~~`, `:=`, labelled
coefficients, transforms). Upstream provides `dag_to_spec()` and
`BuildModelFromDAG`, proving a spec can be mechanically generated from a
DAG. Per `REQ-SCENGINE-001` §1, any adapter must consume the approved
`CausalGraph` and *generate* the spec as derived state, fingerprinting
both the graph (`CausalGraph.structural_fingerprint()`, already
deterministic SHA-256 over structure) and the generated spec. No
workflow may author or edit a spec string directly. The target flow is:

approved `CausalGraph` + estimand + specification
  → capability resolution (before execution, `REQ-SCENGINE-001` §2)
  → generated immutable engine spec (derived state, fingerprinted)
  → engine execution (isolated where F1 applies)
  → governed artefact (engine id/version, runtime identity, graph
    fingerprint, spec fingerprint, support/extrapolation status)

### F3 — Robustness dimensions are split across candidates

PathMC covers D8 (DAG falsification, including a permutation-based
whole-graph test) and D10 (tipping-point sensitivity) natively, but no
treatment-severing placebo refutation is documented upstream. DoWhy
covers D9 (placebo refuter) and D10 natively but is not a Bayesian MMM
engine. No single candidate natively covers all three
`REQ-CAUSALROBUST-001` dimensions; whichever engine is ever approved,
the robustness policy (D2, `VL-028`/`VL-029`) will need to decide which
dimensions come from the engine, which from repo-side diagnostics
(caller-supplies-the-computation pattern used by
`core.estimand_identification`), and which remain unsupported with
explicit status.

### F4 — Count outcomes are supported by PathMC

`REQ-SCEFFECT-001` §2's non-linear/count-outcome requirement maps to
PathMC `families={"Y": "negbinomial"}` (log link, estimated dispersion)
or `"poisson"`. `do()` propagates interventions through transforms
(adstock recomputed over time under the intervention) with full
posterior draws, and warns on out-of-observed-range intervention values
— a support-provenance primitive aligned with `REQ-SCCURVE-001` §2.
Declared endogenous response (§3) is partially expressible (mediators
respond by construction under `do()`; held-fixed semantics per variable
need adapter-level verification before any claim).

### F5 — Ragged coverage is unverified for every candidate

No candidate documents irregular/ragged multi-market panel support
(varying weeks per market). The repository's ragged-coverage handling is
a primary-engine capability. `REQ-SCENGINE-001` §2 requires capability
resolution to include the "ragged-coverage pattern"; any future adapter
evaluation must run a concrete ragged test, or the resolution must
answer "unsupported" explicitly (never silently drop markets).

### F6 — Primary production path unaffected by construction

Per `REQ-SCENGINE-001` §7 and `REQ-SCCURVE-001` §4, this package records
that nothing here proposes changes to the primary PyMC engine, Candidate
A, the sequential simulator (which remains authoritative unless a
separate equivalence proof is approved), curve-bank governance, or
optimisation. The compiler continues to reject every edge role beyond
`direct`/`cross_product_halo`/`excluded_diagnostic_only`/Candidate A's
authorised structure.

## Candidate integration points (anticipated only, not created)

If and when `MD-022` approves an engine, the records' own "Affected
modules" sections anticipate:

- a capability-resolution module (mirroring
  `GraphModelCompiler.check_engine_capability`'s fail-closed pattern,
  with the six-way vocabulary per capability);
- a graph→generated-spec adapter consuming `CausalGraph` and its
  `structural_fingerprint()` (F2);
- persistence extensions: structural causal artefact provenance fields,
  a distinct structural-intervention curve kind in `core.curve_bank`
  (never merged with ordinary response curves), and causal-robustness
  evidence dimensions with mandatory per-dimension non-proof
  disclaimers (`REQ-CAUSALROBUST-001` §2).

None of these modules exist and none is created by this package.

## What this package does and does not decide

Decides / records:

- the current-source capability evidence for PathMC, DoWhy, pgmpy, and
  the no-supplemental-engine baseline, classified per the approved
  six-way vocabulary;
- that PathMC's isolation trigger (`REQ-SCENGINE-001` §4) is factually
  met today (F1);
- that the generated-spec architecture is feasible and mandatory (F2);
- that robustness-dimension coverage is split across candidates (F3).

Does not decide:

- engine selection or eligibility matrix (D1, `MD-022`);
- robustness methods, thresholds, or blocking policy (D2,
  `VL-028`/`VL-029`);
- UX labels and drill-downs (D3, `UX-031`/`UX-032`/`UX-033`);
- any dependency addition, any primary-stack upgrade, any adapter code.

## Real UK end-to-end data validation

`Real UK end-to-end data validation: DEFERRED pending authorised
source-data availability.`

## Sources (all retrieved 2026-08-19)

- PathMC GitHub repository metadata and README:
  `https://github.com/pymc-labs/pathmc` (Apache-2.0, beta, pushed
  2026-08-17).
- PathMC PyPI metadata: `https://pypi.org/pypi/pathmc/json` (0.3.0;
  `requires-python >=3.12`; dependencies `pymc<7,>=6.0`,
  `pytensor<4,>=3.1.1`, `pymc-extras>=0.12`, `numpy>=2.0`, `patsy`,
  `narwhals`, `arviz<2,>=1.1`).
- PathMC documentation: `https://pathmc.pymc-labs.com/` — index,
  `user-guide/model-specification.html` (DSL, latent deterministic
  mediators, residual covariance), `user-guide/transforms-families.html`
  (adstock/logistic_saturation, Gaussian/Bernoulli/Poisson/NegBinomial/
  StudentT families, posterior predictive checks),
  `docs/examples/applied-models/mmm.html` (panel MMM, hierarchical
  random intercepts/slopes, funnel mediation, `do()` counterfactuals,
  extrapolation warnings), `llms.txt` (falsify_graph, TBFPC discovery,
  dag_to_spec, BuildModelFromDAG, custom Transform).
- DoWhy PyPI metadata: `https://pypi.org/pypi/dowhy/json` (0.14; MIT;
  `causal-learn`, `cvxpy`, `numba`, `statsmodels`).
- DoWhy documentation: `https://www.pywhy.org/dowhy/v0.14/`
  (identification/estimation separation, GCMs, refutation/sensitivity
  checks, third-party estimator support).
- pgmpy PyPI metadata: `https://pypi.org/pypi/pgmpy/json` (1.1.2; MIT;
  `networkx>=3.0`, `numpy>=2.0`, `statsmodels`).
- pgmpy README: `https://raw.githubusercontent.com/pgmpy/pgmpy/dev/README.md`
  (DAG/PDAG/MAG/PAG, Bayesian networks, DBNs, SEMs, causal discovery,
  identification, inference, validation metrics, simulations).
- Repository facts (2026-08-19 worktree at green main
  `95e53cccc8f648f8931d8902df34bd1c17cdcd31`): `pyproject.toml` pins
  (`pymc==5.28.5`, `pytensor==2.38.3`, `numpy>=1.24`,
  `pymc-marketing==0.19.2/0.19.4`, `requires-python >=3.11,<3.13`);
  `ancestry_mmm/core/causal_graph.py` (`CausalGraph`,
  `structural_fingerprint()`); `ancestry_mmm/core/graph_model_compiler.py`
  (`GraphModelCompiler.compile`, `check_engine_capability`,
  `_SUPPORTED_EDGE_ROLES`); `ancestry_mmm/core/search_capacity.py`
  (Candidate A); `ancestry_mmm/core/persistence.py`
  (`PROJECT_BUNDLE_SCHEMA_VERSION = 19`, `FHModelMeta` graph identity);
  `ancestry_mmm/core/sequential_simulation.py` (authoritative
  simulator); root `AGENTS.md` "Engine-capability boundary" and
  `ancestry_mmm/core/AGENTS.md` reconciliation rules.
