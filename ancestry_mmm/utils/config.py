"""Configuration constants and defaults for the Ancestry FH MMM app."""

import os
from pathlib import Path

# Default model parameters
DEFAULT_PARAMS = {
    "aggregation": "Weekly",
    "fourier_period": 52,
    "fourier_harmonics": 3,
    "adstock_decay_prior_mean": 0.5,
    "adstock_decay_prior_sd": 0.2,
    "mcmc_draws": 2000,
    "mcmc_tune": 1000,
    "mcmc_chains": 4,
    "mcmc_target_accept": 0.9,
}

# Default FH model priors (see core.hierarchical_model.build_fh_hierarchical_model)
DEFAULT_FH_PRIORS = {
    "decay_mu": 0.5,
    "decay_sigma": 0.2,
    "K_scale": 1.0,
    "K_alpha": 3.0,
    "S_alpha": 4.0,
    "S_beta": 4.0,
    "channel_effect_mu": -2.5,
    "channel_effect_sigma": 0.5,
    "pooling_sigma_prior": 0.3,
    # PR G1 - active_cross_product_sigma/exploratory_cross_product_sigma
    # (core.pathways) replace the old DNA-only "dna_halo_sigma" - same
    # meaning (a channel/outcome cell's cross-product strength prior), now
    # keyed generally rather than assuming the DNA halo pathway is the only
    # cross-product pathway that exists. Kept the same 0.25 default as the
    # old dna_halo_sigma for active_cross_product_sigma (identical legacy
    # behaviour when no pathway catalogue is configured);
    # exploratory_cross_product_sigma defaults tighter (0.08), matching
    # core.hierarchical_model.build_fh_hierarchical_model's own default.
    "active_cross_product_sigma": 0.25,
    "exploratory_cross_product_sigma": 0.08,
    "promo_sigma": 0.5,
    "market_pool_sigma_prior": 0.4,
    "unpooled_market_sigma": 2.0,
    "intercept_sigma": 1.0,
    "trend_sigma": 0.5,
    "fourier_sigma": 0.4,
    "control_sigma": 0.5,
    "alpha_shape": 2.0,
    "alpha_rate": 0.1,
}

DEFAULT_DNA_LAG_WEEKS = 4

# Where generated project data (curve bank entries, calibration records,
# exported project bundles) lives - not committed to the repo, see .gitignore.
CURVE_BANK_ROOT = Path(__file__).parent.parent / ".curve_bank_store"
PROJECT_EXPORT_ROOT = Path(__file__).parent.parent / ".project_exports"

# Official curve artifact store (REQ-CURVE-001, PR 95E) - per-project,
# not committed to the repo, see .gitignore. Overridable via
# MMM_CURVE_ARTIFACT_ROOT so a spawned test/CI instance of the app can be
# pointed at a disposable directory instead of a developer's real local
# store - `replace_curve_artifact_store` is a destructive transactional
# replace, and the default path is shared across every app instance.
CURVE_ARTIFACT_ROOT = Path(
    os.environ.get(
        "MMM_CURVE_ARTIFACT_ROOT",
        str(Path(__file__).parent.parent / ".curve_artifact_store"),
    )
)

# Budget optimization defaults
OPTIMIZATION_DEFAULTS = {
    "min_budget_pct": 0.10,
    "max_budget_pct": 0.80,
    "optimization_method": "marginal_roi",
}

# Chart colours for the internal analytical workbench. These are deliberately
# original to the product rather than copied from the public Ancestry site.
CHART_COLORS = {
    "primary": "#2D6F7A",
    "success": "#2B7A53",
    "warning": "#9A6700",
    "error": "#B13B32",
    "info": "#2D6F7A",
}

CHART_CATEGORICAL = (
    "#2D6F7A",
    "#667A52",
    "#92765D",
    "#7A6F91",
    "#B06A4B",
    "#5A6970",
)

# Role-based analytical theme colours - kept in sync with
# .streamlit/config.toml. The names describe how a colour is used, so page
# presentation does not need to know whether a surface is "brand" or a
# particular public-site campaign colour.
THEME_COLORS = {
    "canvas": "#F4F1EC",
    "surface": "#FFFFFF",
    "surface_subtle": "#F8F7F4",
    "surface_selected": "#E8F0F2",
    "surface_info": "#EDF5F6",
    "surface_warning": "#FBF4E6",
    "surface_error": "#FBECEA",
    "text_primary": "#202725",
    "text_secondary": "#59635F",
    "border_subtle": "#D9D6CF",
    "border_strong": "#B8B9B2",
    "action_primary": "#2D6F7A",
    "action_primary_hover": "#225762",
    "context_accent": "#667A52",
    "success": "#2B7A53",
    "warning": "#9A6700",
    "error": "#B13B32",
    "info": "#2D6F7A",
    "grid": "#E2DFD9",
    "focus_ring": "#6AABB5",
}

# Supported file formats
SUPPORTED_FILE_TYPES = ["csv", "xlsx", "xls"]

# Column type hints for auto-detection
DATE_COLUMN_HINTS = ["date", "week", "month", "day", "time", "period"]
TARGET_COLUMN_HINTS = ["sales", "revenue", "conversions", "kpi", "target", "y"]
SPEND_COLUMN_HINTS = ["spend", "cost", "budget", "investment", "media"]
