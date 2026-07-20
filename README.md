# Marketing Mix Modelling - Complete Example

A practical implementation of Marketing Mix Modelling (MMM) using Bayesian methods, based on the concepts from [Marketing Mix Modelling: The Complete Guide](MMM_Complete_Guide_v7.docx) by Mark Stent.

## About This Project

The accompanying guide was written to incorporate as many MMM concepts as possible into a single resource. However, it's important to note:

- **Not exhaustive**: The guide doesn't cover every aspect of MMM - it's a comprehensive starting point, not the final word
- **Bayesian focus**: This implementation uses Bayesian methods exclusively. There are other valid approaches (frequentist regression, machine learning methods, etc.) that are not covered here
- **Two implementations**: This repository includes both additive and multiplicative model specifications, demonstrating different approaches to MMM

The goal is to provide a solid foundation for understanding and implementing Bayesian MMM, which you can then adapt to your specific needs.

## Project Structure

```
MMM-guide/
├── notebooks/                  # Jupyter notebooks with full MMM examples
│   ├── mmm_complete_example.ipynb       # Additive model
│   └── mmm_multiplicative_example.ipynb # Multiplicative model
├── ancestry_mmm/                # Actively developed app - see below
├── archive/                    # Archived stacks (dashboard/, backend/, frontend/) - see archive/README.md
├── conjura_mmm_data.csv       # Raw dataset used by archive/dashboard/
├── pyproject.toml             # Python dependencies
└── README.md
```

## Notebooks

All notebooks are located in the `notebooks/` folder.

| Notebook | Model Type | Description |
|----------|------------|-------------|
| `notebooks/mmm_complete_example.ipynb` | **Additive** | Standard MMM: `Sales = Baseline + Media_Effects + Controls` |
| `notebooks/mmm_multiplicative_example.ipynb` | **Multiplicative** | Log-log and lift-factor models with Shapley decomposition |

### When to Use Each

- **Additive Model**: Simpler interpretation, straightforward decomposition, works well for most cases
- **Multiplicative Model**: Better when channels interact strongly, coefficients are elasticities, requires Shapley values for attribution

## Web Application (archived)

The project previously included a separate no-code web application ("MMMpact": FastAPI + Next.js)
alongside a generic single-KPI "MMM Studio" Streamlit dashboard. Both are now archived under
`archive/` — see `archive/README.md` for why (in short: MMMpact does not run as committed, and
the dashboard's results/optimisation pages presented some fabricated numbers). `ancestry_mmm/`
(below) is the actively developed application.

## Ancestry FH MMM & Scenario Planner

`ancestry_mmm/` is a separate Streamlit application, built from the MMM Studio codebase above but
re-scoped around Ancestry's actual Family History (FH) measurement problem rather than a generic
single-KPI MMM. See `docs/ancestry_fh_mmm.md` for the full requirements brief this build serves.

### Why a separate app, not just a config change

Ancestry's FH acquisition splits into three paths with materially different media response,
promotional sensitivity and value - **New**, **DNA cross-sell**, **Winback** - plus a DNA-media
halo effect that needs to be tracked explicitly. A blended single-KPI model (what the archived
`archive/dashboard/` MMM Studio codebase provides) hides all of that. `ancestry_mmm/` models the
three segments **jointly**: shared
channel-level adstock/saturation curves, segment-specific response strength via partial pooling,
an explicit lagged DNA halo pathway, and segment-specific promo sensitivity - see
`ancestry_mmm/core/hierarchical_model.py`.

### What's built (Phase 1 core + scenario planner + basic persistence)

- **Data pipeline**: multi-source upload (media/outcomes/controls), joined on date + market;
  an ordered, replayable transformation pipeline (`ancestry_mmm/data/pipeline.py`) - calculated
  columns use a restricted expression parser (`ast`-based allowlist), not `eval()`; validation
  checks for low-variance channels, collinearity, and sparse segments/markets before fitting.
- **Joint hierarchical model**: one Negative-Binomial model per market covering all FH segments,
  shared adstock/Hill-saturation curves, segment multipliers via partial pooling, an explicit
  lagged DNA halo pathway, segment-specific promotional sensitivity, and a geo hierarchy (UK /
  Australia / Canada in the demo data) with a per-market "unpooled" override.
- **Diagnostics scorecard**: convergence (R-hat/ESS/divergences), in-sample fit, posterior
  predictive coverage, curve/ROI plausibility flags, and an expanding-window out-of-sample
  backtest (`ancestry_mmm/core/diagnostics.py`).
- **Curve bank**: versioned, JSON-backed storage of each run's shared curves and segment
  parameters, traceable to its data window and run label, plus a geo-test/in-platform-test
  calibration log with an agree/diverge flag (`ancestry_mmm/core/curve_bank.py`).
- **Attribution**: Shapley-decomposed segment + total-FH contributions (order-independent, sums
  exactly to the model's predicted total), ROAS/CPA by channel x segment, LTV-weighted value.
- **Scenario planner**: manual editing, constrained optimisation (locked cells, fixed channel/month
  totals, bounded movement, minimum-spend floors), and a clearly-labelled unconstrained benchmark -
  all evaluated with a documented steady-state response approximation, not literal MCMC-in-the-loop
  (`ancestry_mmm/core/optimization.py`, `ancestry_mmm/core/predict.py`).
- **Project persistence**: a downloadable/re-importable bundle (Parquet + JSON + NetCDF, all open
  formats - `ancestry_mmm/core/persistence.py`) and an Excel export for stakeholders who consume
  spreadsheets, not code.
- **Synthetic demo data**: `ancestry_mmm/sample_data/generate_sample_data.py` produces a synthetic
  UK/Australia/Canada dataset shaped like the real problem (not real Ancestry data), so the app is
  runnable end-to-end before real data is connected.

### Explicitly not built yet

PowerPoint export, real Australia/Canada market builds (the geo hierarchy machinery is implemented
and exercised by the synthetic 3-market demo, but needs real data to mean anything), a live feed
from geo-tests/in-platform tests into the curve bank (the comparison/logging workflow exists; the
feed is manual), and Stage 2 media x context interaction terms (explicitly out of scope per the brief).

### Running it

```bash
uv sync
uv run streamlit run ancestry_mmm/app.py
```

## Dataset

This project uses the [Multi-Region Marketing Mix Modeling Dataset](https://figshare.com/articles/dataset/Multi-Region_Marketing_Mix_Modeling_MMM_Dataset_for_Several_eCommerce_Brands/25314841) from Figshare, which contains e-commerce marketing data across multiple brands and channels.

## Topics Covered

### Additive Model (`notebooks/mmm_complete_example.ipynb`)

#### Part I: Data Foundations
- Loading and exploring marketing data
- Selecting appropriate data granularity (weekly aggregation)
- Exploratory data analysis

#### Part II: Data Preprocessing
- Handling missing values
- Identifying and handling outliers
- Scaling variables for modelling
- Creating derived variables

#### Part III: Multicollinearity Analysis
- Correlation matrix between channels
- Interpreting correlation levels
- Strategies for handling high correlation

#### Part IV: Media Transformations
- **Adstock (Carryover Effects)**: Geometric adstock transformation
- **Saturation (Diminishing Returns)**: Hill function implementation
- Complete transformation pipeline

#### Part V: Bayesian Model Building
- Prior specification (informed by domain knowledge)
- Complete model structure in PyMC
- MCMC sampling

#### Part VI: Convergence Diagnostics
- R-hat interpretation
- Effective Sample Size (ESS)
- Trace plot analysis

#### Part VII: Model Validation
- In-sample fit (R-squared, MAPE)
- Residual analysis
- Posterior predictive checks
- LOO-CV (Leave-One-Out Cross-Validation)

#### Part VIII: Results Analysis
- Response curves with uncertainty
- ROI calculation with credible intervals
- Sales decomposition
- Channel contribution analysis

#### Part IX: Budget Optimisation
- Marginal ROI calculation
- Optimal budget allocation
- Constraint handling

### Multiplicative Model (`notebooks/mmm_multiplicative_example.ipynb`)

Covers the same data preparation as the additive model, plus:

- **Log-Log Specification**: Elasticity-based model where coefficients represent % change
- **Lift-Factor Specification**: Multiplicative lifts from baseline with natural interactions
- **Shapley Value Decomposition**: Fair attribution for multiplicative models
- **Model Comparison**: Side-by-side comparison of both multiplicative approaches
- **Budget Optimization**: Allocation optimization using elasticities

Key differences from additive:
```
Additive:       Sales = Baseline + b1*X1 + b2*X2
Log-Log:        log(Sales) = a + b1*log(X1) + b2*log(X2)
Lift-Factor:    Sales = Baseline * (1 + lift_1) * (1 + lift_2)
```

## Setup

### Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager

### Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd MMM-guide
```

2. Install Python dependencies using uv:
```bash
uv sync
```

3. Start Jupyter Lab for notebooks:
```bash
uv run jupyter lab
```

4. Open `notebooks/mmm_complete_example.ipynb` and run the cells

### Dependencies

Key packages used:
- **PyMC**: Bayesian modelling framework
- **ArviZ**: Bayesian diagnostics and visualization
- **Pandas/NumPy**: Data manipulation
- **SciPy**: Optimization algorithms
- **FastAPI**: Backend API server
- **Next.js/React**: Web frontend
- **Recharts**: Interactive charts

## Key Concepts

### The MMM Equation (Additive)
```
Sales = Baseline + Trend + Seasonality + Media_Effects + Noise
```

### The MMM Equation (Multiplicative)
```
Sales = Baseline * (1 + TV_lift) * (1 + Digital_lift) * Seasonality * exp(Noise)
```
Or in log-log form:
```
log(Sales) = alpha + elasticity_TV * log(TV) + elasticity_Digital * log(Digital) + ...
```

### Adstock Transformation
Models how advertising effects persist over time:
```
Adstock(t) = Spend(t) + lambda * Adstock(t-1)
```

### Hill Saturation Function
Models diminishing returns:
```
Response = x^S / (K^S + x^S)
```

Where:
- **K**: Half-saturation point (spend level at 50% effect)
- **S**: Shape parameter (controls curve steepness)

### Budget Optimization

The optimizer uses the log-log model formula to maximize total sales:
```
contribution = avg_sales * (spend / avg_spend)^elasticity
```

At the optimal allocation, marginal ROI is equalized across all channels.

## References

- Mark Stent, [Marketing Mix Modelling: The Complete Guide](MMM_Complete_Guide_v7.docx)
- [Figshare Dataset](https://figshare.com/articles/dataset/Multi-Region_Marketing_Mix_Modeling_MMM_Dataset_for_Several_eCommerce_Brands/25314841)
- [PyMC Documentation](https://www.pymc.io/)
