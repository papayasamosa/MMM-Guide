# UK common-window joint-model remediation

## Authority and scope

This record implements the approved task brief supplied with
`Ancestry_MMM_Common_Window_Joint_Model_Convergence_and_Search_Next_Steps.md`
(received 2026-08-22). The brief governs this historical test and therefore
overrides the earlier longer UK readiness window only for this test run. It
does not alter the immutable earlier readiness artefacts.

The business question is whether the UK Family History and DNA product
outcomes can be estimated in two coherent shared/hierarchical PyMC models
over one common, fully supported historical window. The fitted estimand is
the posterior distribution of weekly outcome-scale expected counts and their
draw-level product totals under the approved media-input transformations and
controls. Monetary CPA/ROI and optimisation remain downstream governed uses;
no value weights are invented here.

## Approved preparation contract

- The common Sunday-Saturday likelihood window is `2023-01-01` through
  `2025-04-06` (119 weeks). Pre-window media history is retained for
  carry-in/adstock; it is not included in the likelihood.
- Family History is one joint model with New NBT, DNA cross-sell NBT, and
  Winback NBT. DNA is a separate joint model with New Customer and Existing
  Family History Customer kit outcomes. There is no five-outcome model.
- Historical `fh_gsa_*` identifiers are migrated only at the explicit fit
  boundary to canonical `fh_net_billthrough_count_*` identifiers. Raw source
  columns and source workbooks are unchanged; the legacy names are not
  emitted as GSA model/report identifiers.
- Native weekly Family History and DNA category-demand series are the only
  consumed Model-A context candidates. Monthly CPIH, unemployment, mortgage,
  deaths (Family History only), and other monthly candidates remain blocked
  until source release timing and a governed release-aware method exist.
  No values are repeated, interpolated, or zero-filled.
- DNA Performance Social remains retained but excluded because four required
  impression observations are unavailable. Branded Paid Search remains
  retained for diagnostics/sensitivity but is excluded from the official
  causal contribution calculation until the governed Search decomposition is
  available.
- With one UK market, between-market variance is not estimated. The existing
  multi-market partial-pooling branch remains intact.
- Product totals are formed by summing member outcomes within each posterior
  draw before calculating summaries; separately summarised segment rows are
  never added together.

## Implementation and evidence

The runner now emits preparation evidence for the target window, outcome
identity migration, context status, model dimensions, shared hierarchy
variables, and the one-market hierarchy bypass. The outcome catalogue
migration is explicit and reversible at the source boundary; it is not a
workbook mutation.

The D-drive environment was verified with PyMC 5.28.5, PyTensor 2.38.3,
ArviZ 0.23.4, and PyMC-Marketing 0.19.4. The authorised D-drive MinGW-w64
compiler was used with a D-drive PyTensor compiledir. A small PyTensor C++
compile and a small PyMC/NUTS sampling path passed. The implementation uses
PyMC and remains aligned with `docs/pymc_marketing_alignment.md`; it does not
switch to JAX/NumPyro.

Preparation and regression evidence is held outside Git under
`D:\Ancestry-MMM\test-artifacts\historical-common-window-readiness-20260822`.
The earlier 131-week artefacts remain immutable. No real posterior or raw
source data is committed to this branch.

## Remaining gate

The common-window preparation gate passes, but the real 119-week NUTS fit is
not certified. A bounded Family History stage-1 attempt compiled successfully
but produced no completed chain within a responsible runtime bound and was
stopped before diagnostics existed. The small production-path smoke sampler
passed, while the host showed a NumPy C-API BLAS fallback and very slow graph
execution. The earlier full fit also required hours per product and had
divergences/R-hat failures.

Therefore Model A convergence is still an explicit runtime/convergence gate;
Model B Search mediation and Model C are not started. The correct next action
is to diagnose or improve the approved PyMC/PyTensor runtime, then execute the
brief's staged convergence protocol and require zero divergences where
possible, R-hat at most 1.01, healthy ESS/BFMI/treedepth/MCSE, and posterior
predictive checks before any official attribution or optimisation use.

## Upstream alignment

The implementation follows the repository's recorded PyMC/PyMC-Marketing
policy and the local pinned sources consulted for adstock and saturation:
`pymc_marketing.mmm.components.adstock` and
`pymc_marketing.mmm.components.saturation` at PyMC-Marketing 0.19.4. The
custom code is limited to Ancestry's approved outcome identity migration,
joint product outcome wiring, one-market hierarchy handling, context
governance, and draw-level product rollups.
