# Historical UK MMM validation

`scripts/run_historical_mmm_validation.py` is the read-only historical
reference gate for the updated UK workbooks. It writes artefacts to
`D:\Ancestry-MMM\test-artifacts\historical-mmm-validation-20260821` by
default and never edits the raw workbooks or the saved previous posterior
files.

It performs four bounded activities:

1. audits the updated outcome/activity/context workbooks against the governed
   Sunday-Saturday window, preserving native frequencies and reporting exact
   missing coverage;
2. reconstructs the previous FH and DNA Model A specifications from the
   immutable approved source pack and saved fit report, then generates
   posterior-predictive, residual, Bayesian R-squared, convergence, and
   LOO/WAIC evidence without refitting;
3. records the observed Paid Brand Search mediation specification and the
   separate spend/delivery Search identities; and
4. starts a revised fit only when coverage and approved graph preparation
   pass. A blocked preparation gate leaves the revised posterior absent and
   records the reason rather than shortening or filling the window.

Run it with the governed D-drive PyMC runtime:

```powershell
$env:PATH = "D:\Ancestry-MMM\tools\mingw64\bin;$env:PATH"
$env:PYTENSOR_FLAGS = "cxx=D:/Ancestry-MMM/tools/mingw64/bin/g++.exe,base_compiledir=D:/Ancestry-MMM/cache/pytensor"
& D:\Ancestry-MMM\venvs\mmm-guide-py31213\Scripts\python.exe `
  scripts\run_historical_mmm_validation.py
```

The current reference run is blocked because the updated activity workbook
does not provide the required target-window observations through
`2025-06-29`, and its raw outcome dictionary leaves some approved governance
flags blank. The report records the approved derived run overlay while
keeping those raw source issues visible for correction.

The revised model is not authorised to generate curves, planning, or
optimisation artefacts from this blocked run.

## Historical remediation and pre-fit package

`scripts/run_historical_mmm_remediation.py` is the follow-on, versioned
readiness runner. It writes a new package under
`D:\Ancestry-MMM\test-artifacts\historical-mmm-remediation-20260821` and
leaves both the raw workbooks and the previous validation/posterior package
unchanged. It reconciles raw activity against the approved structural-zero
pack, migrates only the three corrected Family History NBT identities, adds
the complete retrospective scorecard, executes the supported Sunday-week
mixed-frequency methods, and writes candidate graph/Search/identification
evidence.

The current run has zero required activity fit blockers and resolves all
three NBT migrations. DNA Performance Social remains retained but excluded
from the initial DNA fit because four impression cells are unavailable.
The candidate causal graph remains draft, and the governed Search
demand/cap/organic/direct decomposition is not complete. Therefore the
runner stops before any revised real-data fit with the recommendation:
**2. governance/graph approval required**.

Run it with the authorised D-drive runtime after setting the compiler and
PyTensor cache explicitly:

```powershell
$env:PATH = "D:\Ancestry-MMM\tools\mingw64\bin;$env:PATH"
$env:PYTENSOR_FLAGS = "cxx=D:/Ancestry-MMM/tools/mingw64/bin/g++.exe,base_compiledir=D:/Ancestry-MMM/cache/pytensor"
& D:\Ancestry-MMM\venvs\mmm-guide-py31213\Scripts\python.exe `
  -m scripts.run_historical_mmm_remediation
```
