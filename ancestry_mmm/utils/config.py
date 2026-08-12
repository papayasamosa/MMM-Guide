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

# Chart colours for the light analytical workbench. Brand blue/green are used
# sparingly; semantic success/warning/error remain distinct from brand identity.
CHART_COLORS = {
    "primary": "#117FA6",
    "chart_1": "#117FA6",  # Ancestry-inspired blue
    "chart_2": "#6BA410",  # Brand-inspired green
    "chart_3": "#A66A00",  # Amber
    "chart_4": "#B85C38",  # Terracotta
    "chart_5": "#6D5A9E",  # Restrained violet
    "chart_6": "#5F6B65",  # Neutral slate
    "success": "#287A43",
    "warning": "#A66A00",
    "error": "#B42318",
    "info": "#117FA6",
}

# Light, warm analytical theme colours - kept in sync with
# .streamlit/config.toml. Brand identity and semantic status intentionally
# use separate tokens.
THEME_COLORS = {
    "background": "#F6F3F0",
    "background_secondary": "#FFFFFF",
    "card": "#FFFFFF",
    "foreground": "#202923",
    "foreground_muted": "#5F6B65",
    "border": "#D8D4CE",
    "accent": "#117FA6",
    # Darkened for readable small text; chart accents retain the lighter green.
    "brand_accent": "#4E7D1A",
    "selected": "#E7F2F5",
    "grid": "#DDD9D3",
}

# Supported file formats
SUPPORTED_FILE_TYPES = ["csv", "xlsx", "xls"]

# Column type hints for auto-detection
DATE_COLUMN_HINTS = ["date", "week", "month", "day", "time", "period"]
TARGET_COLUMN_HINTS = ["sales", "revenue", "conversions", "kpi", "target", "y"]
SPEND_COLUMN_HINTS = ["spend", "cost", "budget", "investment", "media"]
