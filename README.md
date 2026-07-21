# Ancestry FH MMM & Scenario Planner

An in-house Bayesian Marketing Mix Modelling (MMM) workbench and scenario planner, built around
Ancestry's actual Family History (FH) measurement problem: **New**, **DNA cross-sell** and
**Winback** acquisition paths modelled jointly - not collapsed into a single blended KPI - plus an
explicit DNA-to-FH halo pathway, a versioned curve bank, an explicit model-approval gate, and
constrained scenario planning.

The application lives in [`ancestry_mmm/`](ancestry_mmm/) and runs as a Streamlit app. See
[`docs/ancestry_fh_mmm.md`](docs/ancestry_fh_mmm.md) for the full requirements brief it was built
against - why segments are modelled jointly, why the DNA halo pathway is explicit, why the
scenario planner defaults to constrained rather than unconstrained optimisation, and why the model
approval gate exists.

## Quick start

```bash
uv sync
uv run streamlit run ancestry_mmm/app.py
```

Opens at `http://localhost:8501`. From there: **Data Upload** → click "Load synthetic demo
sources" for a working UK/Australia/Canada dataset with no setup required, then work through the
sidebar in order (Transform Pipeline → Structure → Channel & Media Units → Market Descriptors →
Model Configuration → Model Training → Compare Models → Diagnostics → Results & Curve Bank →
Scenario Planner → Project Export & Handover).

Requires Python 3.11 or 3.12 (see [Deployment](#deployment) below for why there's an upper bound).

## What it does

- **Joint hierarchical model** (`ancestry_mmm/core/hierarchical_model.py`, "Model A"): one
  Negative-Binomial model per market covering all FH segments together, with one **shared**
  channel-level adstock/Hill saturation curve across markets, segment-specific response strength
  via partial pooling, an explicit lagged DNA halo pathway (not a fixed multiplier),
  segment-specific promotional sensitivity, and a geo hierarchy (UK / Australia / Canada in the
  demo data) with a per-market "unpooled" override.
- **Market-specific model** (`ancestry_mmm/core/market_specific_model.py`, "Model C"): the same
  joint FH structure, but with **market-specific, partially-pooled** channel curves
  (`docs/market_hierarchy.md`) - a smaller market borrows strength from larger ones instead of
  being forced to match a shared curve exactly or fitted alone with no support. Model B
  (fully independent per-market fits) is available as a comparison baseline via
  `core.model_comparison`, not as a production default. `pages/12_Compare_Models.py` compares
  fitted candidates side by side before either is adopted.
- **Evidence tiers** (`ancestry_mmm/core/evidence_tiers.py`): every Model C curve bank entry is
  labelled `Locally estimated`, `Partially pooled`, or `Transferred estimate` based on
  observation count and posterior uncertainty, so a market with too little data to trust isn't
  presented as if it had a precisely estimated curve.
- **Media units and CPA** (`ancestry_mmm/core/media_units.py`): optional per-(market, channel)
  spend-to-physical-delivery mapping (Channel & Media Units page), average/marginal CPA at every
  curve point, response-unit curves, and media cost inflation tracking - an assumed future cost
  is always an explicit, visible input, never applied silently.
- **Data pipeline** (`ancestry_mmm/data/pipeline.py`): multi-source upload (media/outcomes/
  controls) joined on date + market, an ordered and replayable transformation pipeline, calculated
  columns via a restricted `ast`-based expression parser (not `eval()`), and validation checks for
  low-variance channels, collinearity, and sparse segments/markets before fitting.
- **Diagnostics scorecard** (`ancestry_mmm/core/diagnostics.py`): convergence (R-hat/ESS/
  divergences), in-sample fit, posterior predictive coverage, curve/ROI plausibility flags, and an
  expanding-window out-of-sample backtest.
- **Model approval gate** (`ancestry_mmm/core/approval.py`): a high R-squared isn't a reason to
  accept a model on its own - an explicit approval (reviewer, notes, known limitations, which
  diagnostics were checked) is required before a model's curves can be saved to the curve bank or
  used in the Scenario Planner. Curve bank entries structurally cannot be created without one.
- **Curve bank** (`ancestry_mmm/core/curve_bank.py`): versioned, JSON-backed, append-only storage
  of each approved run's curves and segment parameters - one shared curve per channel for Model A,
  one per (market, channel) for Model C, each carrying its evidence tier - traceable to its data
  window, approver and run label, plus a geo-test/in-platform-test calibration log with an
  agree/diverge flag (Model A only).
- **Attribution** (`ancestry_mmm/core/attribution.py`, `ancestry_mmm/core/market_specific_attribution.py`):
  Shapley-decomposed segment and total-FH contributions (order-independent, sums exactly to the
  model's predicted total), ROAS/CPA by channel x segment, LTV-weighted value - available for both
  model types; Model C's decomposition is market-aware (each row uses its own market's `beta`/
  `hill_K`, not a single shared curve).
- **Posterior uncertainty** (`ancestry_mmm/core/uncertainty.py`): opt-in credible intervals for
  response curves and scenario outcomes, computed by re-running the same point-estimate calculation
  once per sampled posterior draw (a subsample, for speed) and summarizing the resulting
  distribution - alongside, never in place of, the point estimate.
- **Scenario planner** (`ancestry_mmm/core/optimization.py`, `ancestry_mmm/core/predict.py`):
  manual editing, constrained optimisation (locked cells, fixed channel/month totals, bounded
  movement, minimum-spend floors), and a clearly-labelled unconstrained benchmark - market-aware
  for Model C, with a media-unit planning mode - all evaluated with a documented steady-state
  response approximation using the model's real fitted curves, not literal MCMC-in-the-loop.
- **Project persistence** (`ancestry_mmm/core/persistence.py`): a downloadable/re-importable
  bundle (Parquet + JSON + NetCDF, all open formats), with path-traversal-safe zip import, an
  Excel export for stakeholders who consume spreadsheets, not code, and a reproducible Markdown/
  HTML project report (`ancestry_mmm/core/report.py`) built from the project's actual current
  state.
- **Synthetic demo data** (`ancestry_mmm/sample_data/generate_sample_data.py`): a synthetic UK /
  Australia / Canada dataset shaped like the real problem (three FH segments, a DNA-targeted media
  channel with a known halo effect, known adstock/saturation) - not real Ancestry data - so the
  app is runnable end-to-end before real data is connected.

### Why segments are modelled jointly, not as one blended KPI

Ancestry's FH acquisition splits into three paths with materially different media response,
promotional sensitivity and value - **New**, **DNA cross-sell**, **Winback** - plus a DNA-media
halo effect that needs to be tracked explicitly. A blended single-KPI model hides all of that.
`ancestry_mmm/` models the three segments **jointly**: shared channel-level adstock/saturation
curves, segment-specific response strength via partial pooling, an explicit lagged DNA halo
pathway, and segment-specific promo sensitivity.

### What's explicitly not built yet

PowerPoint export, real Australia/Canada market builds (the geo hierarchy machinery is implemented
and exercised by the synthetic 3-market demo, but needs real data to mean anything), a live feed
from geo-tests/in-platform tests into the curve bank (the comparison/logging workflow exists; the
feed is manual), and Stage 2 media x context interaction terms (explicitly out of scope per the
requirements brief).

## Project structure

```
.
├── ancestry_mmm/            # The application
│   ├── app.py                #   Entry point: streamlit run ancestry_mmm/app.py
│   ├── core/                 #   Modelling, attribution, curve bank, optimisation, persistence
│   ├── data/                 #   Loader, transform pipeline, preprocessor
│   ├── pages/                #   One Streamlit page per workflow stage
│   ├── components/           #   Chart helpers
│   ├── utils/                #   Session-state and config helpers
│   ├── sample_data/           #   Synthetic UK/Australia/Canada demo data generator
│   └── tests/                #   pytest suite
├── docs/
│   └── ancestry_fh_mmm.md    # The product/requirements brief ancestry_mmm/ was built against
├── archive/                  # Superseded stacks, kept for reference - see archive/README.md
├── mmm_complete_example.ipynb          # Reference notebook: additive Bayesian MMM
├── mmm_multiplicative_example.ipynb    # Reference notebook: log-log / lift-factor MMM
├── MMM_Complete_Guide_v7.docx          # Companion textbook the reference notebooks are based on
├── conjura_mmm_data*.{csv,xlsx}        # Demo dataset used by the archived MMM Studio dashboard
├── runtime.txt / .python-version       # Pin Python to 3.11-3.12 (pymc/pytensor don't support 3.13+ yet)
└── pyproject.toml
```

## Testing and checks

```bash
uv run pytest ancestry_mmm/tests/    # unit + integration tests
uv run ruff check ancestry_mmm/      # linting
```

The suite covers the safe zip-import path (path-traversal protection), project export/import
round-tripping, the model-approval gate, curve bank versioning, the transformation pipeline's
restricted expression parser, adstock/saturation math, and `ModelSpec` validation.

## Deployment

`ancestry_mmm/app.py` deploys as a standard Streamlit app (e.g. Streamlit Community Cloud: point
it at this repo with main file path `ancestry_mmm/app.py`). `requires-python` in `pyproject.toml`
and `runtime.txt` both pin Python to `>=3.11,<3.13` - pymc/pytensor have no released build for
Python 3.13+ yet, so hosts that default to the newest available interpreter will otherwise fail
dependency resolution.

Model Training runs real PyMC/NUTS MCMC sampling, which is memory- and CPU-intensive - expect it
to be slow (or to hit resource limits) on free-tier hosting.

## Archived: earlier codebases

`archive/` holds two earlier stacks superseded by `ancestry_mmm/` - a generic single-KPI "MMM
Studio" Streamlit dashboard, and a separate FastAPI + Next.js no-code web app ("MMMpact") that
never ran as committed. See [`archive/README.md`](archive/README.md) for details. Nothing in
`ancestry_mmm/` depends on either.

## Reference material: Bayesian MMM notebooks

Two standalone Jupyter notebooks at the repo root are a companion to [Marketing Mix Modelling: The
Complete Guide](MMM_Complete_Guide_v7.docx) by Mark Stent, and are independent of the
`ancestry_mmm/` application - useful for learning the underlying Bayesian MMM techniques
(adstock, saturation, MCMC diagnostics, attribution, budget optimisation), not for running the
Ancestry-specific tool.

| Notebook | Model type | Description |
|----------|------------|--------------|
| `mmm_complete_example.ipynb` | Additive | `Sales = Baseline + Media_Effects + Controls`, with adstock, Hill saturation, PyMC model building, convergence diagnostics, and budget optimisation |
| `mmm_multiplicative_example.ipynb` | Multiplicative | Log-log (elasticity) and lift-factor specifications, plus Shapley decomposition for multiplicative models |

Run them with:

```bash
uv run jupyter lab
```

They use a separate e-commerce dataset from the [Multi-Region Marketing Mix Modeling
Dataset](https://figshare.com/articles/dataset/Multi-Region_Marketing_Mix_Modeling_MMM_Dataset_for_Several_eCommerce_Brands/25314841)
on Figshare - unrelated to the synthetic Ancestry demo data used by `ancestry_mmm/`.

## References

- [`docs/ancestry_fh_mmm.md`](docs/ancestry_fh_mmm.md) - the requirements brief `ancestry_mmm/` was built against
- Mark Stent, [Marketing Mix Modelling: The Complete Guide](MMM_Complete_Guide_v7.docx)
- [PyMC documentation](https://www.pymc.io/)
