# UK lifecycle readiness harness

The WP5 harness is a local, metadata-only readiness boundary. It reuses the
standard source-pack parser/adoption path, the native-frequency official
preparation gate, the consumed-variable capability report, and the existing
deterministic lifecycle bundle fixture. It does not fit a live model, convert
mixed-frequency data, infer coverage treatment, create approvals, or print
source rows.

## Synthetic CI run

From the repository root on Windows:

```powershell
uv run python scripts\run_uk_readiness.py `
  --synthetic `
  --synthetic-case pass `
  --output-dir "D:\Ancestry-MMM\test-artifacts\uk-readiness"
```

The pass case exercises source parsing, native weekly preparation, engine
capability, deterministic model/approval/curve/scenario evidence, and export,
import, and resumability. The other deterministic cases are useful for
fail-closed checks:

```powershell
uv run python scripts\run_uk_readiness.py --synthetic --synthetic-case mixed_frequency `
  --output-dir "D:\Ancestry-MMM\test-artifacts\uk-readiness-mixed"
uv run python scripts\run_uk_readiness.py --synthetic --synthetic-case coverage_gap `
  --output-dir "D:\Ancestry-MMM\test-artifacts\uk-readiness-gap"
```

The command exits `0` only for the synthetic pass case. A blocked,
unsupported, or decision-required result exits `2`; invalid input or an
execution failure exits `1`.

## Authorised real UK run

An authorised analyst must place the local source workbooks or project bundle
on the D: drive and run the harness with explicit logical domains and the
approved project calendar. The example below uses the standard source-pack
domains; replace the paths with the approved local files.

```powershell
uv run python scripts\run_uk_readiness.py `
  --source "outcomes=D:\Ancestry-MMM\uk-source\outcomes.xlsx" `
  --source "activity=D:\Ancestry-MMM\uk-source\activity-and-media.xlsx" `
  --source "context=D:\Ancestry-MMM\uk-source\context-and-external-factors.xlsx" `
  --source "experiments=D:\Ancestry-MMM\uk-source\experiment-evidence.xlsx" `
  --governed-start YYYY-MM-DD `
  --governed-end YYYY-MM-DD `
  --governed-frequency weekly `
  --output-dir "D:\Ancestry-MMM\test-artifacts\uk-readiness"
```

For an existing project bundle:

```powershell
uv run python scripts\run_uk_readiness.py `
  --bundle "D:\Ancestry-MMM\uk-source\project-bundle.zip" `
  --output-dir "D:\Ancestry-MMM\test-artifacts\uk-readiness"
```

Review `uk-readiness-report.json` for source counts, schema and source-version
identity, fingerprints, date coverage, missingness counts, stage status, and
timings. The report contains no source rows or parsed source values. Keep the
report and any generated bundle on D: and outside the repository; do not copy
real Ancestry data, reports, or logs into Git or browser artefact directories.

## Approved UK production fit

The approved production run uses PyMC with PyTensor and the portable compiler
under `D:\Ancestry-MMM\tools\mingw64`. Use the repository wrapper so the
compiler and PyTensor compilation cache are selected explicitly on D: and are
not taken from an ambient installation:

```powershell
scripts\run_uk_production_fit.ps1 `
  --pack-dir "D:\Ancestry-MMM\test-artifacts\uk-readiness\approved-uk-packs-20260820-v3" `
  --output-dir "D:\Ancestry-MMM\test-artifacts\uk-readiness\production-fit-20260820"
```

The wrapper sets `PYTENSOR_FLAGS` with `cxx=D:/Ancestry-MMM/tools/mingw64/bin/g++.exe`
and `base_compiledir=D:/Ancestry-MMM/cache/pytensor` for the child process. It
does not switch to JAX/NumPyro or install machine-wide tooling. Keep real fit
artefacts outside Git and review convergence, posterior predictive evidence,
and governance approval before using results for official reporting or
optimisation.

The harness stops at unresolved governance or decision boundaries. In
particular, mixed-frequency variables remain native and unconverted, missing
coverage remains unresolved, and a real source-only run does not claim model
fit, approval, curves, planning, or resumability. The harness does not choose
the required statistical or causal method.
