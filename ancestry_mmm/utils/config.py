"""Configuration constants and defaults for the Ancestry FH MMM app."""

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

# Budget optimization defaults
OPTIMIZATION_DEFAULTS = {
    "min_budget_pct": 0.10,
    "max_budget_pct": 0.80,
    "optimization_method": "marginal_roi",
}

# Chart colors matching the design system - a professional dark-green palette.
# "primary"/"success" reuse the one accent green everywhere (buttons, active nav,
# links, selected controls, focus states, success states); chart_1..chart_6 are a
# qualitative palette for multi-series charts, deliberately avoiding navy/blue/
# purple and neon green.
CHART_COLORS = {
    "primary": "#34A871",
    "chart_1": "#34A871",  # Accent green
    "chart_2": "#2FB6A3",  # Teal
    "chart_3": "#D9A441",  # Amber/gold
    "chart_4": "#C97B4A",  # Terracotta
    "chart_5": "#8FA33E",  # Olive
    "chart_6": "#6B8B7A",  # Muted slate-green
    "success": "#34A871",
    "warning": "#D9A441",
    "error": "#E2555B",
    "info": "#6B8B7A",
}

# Dark green-charcoal theme colors - kept in sync with .streamlit/config.toml.
THEME_COLORS = {
    "background": "#0E1512",
    "background_secondary": "#16211B",
    "card": "#16211B",
    "foreground": "#F1F5F1",
    "foreground_muted": "#93A398",
    "border": "#2C3D33",
    "accent": "#34A871",
}

# Supported file formats
SUPPORTED_FILE_TYPES = ["csv", "xlsx", "xls"]

# Column type hints for auto-detection
DATE_COLUMN_HINTS = ["date", "week", "month", "day", "time", "period"]
TARGET_COLUMN_HINTS = ["sales", "revenue", "conversions", "kpi", "target", "y"]
SPEND_COLUMN_HINTS = ["spend", "cost", "budget", "investment", "media"]
