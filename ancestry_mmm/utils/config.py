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
    "dna_halo_sigma": 0.25,
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

# Chart colors matching the design system
CHART_COLORS = {
    "primary": "#4F46E5",
    "chart_1": "#4F46E5",  # Indigo
    "chart_2": "#06B6D4",  # Cyan
    "chart_3": "#10B981",  # Emerald
    "chart_4": "#F59E0B",  # Amber
    "chart_5": "#EC4899",  # Pink
    "chart_6": "#8B5CF6",  # Purple
    "success": "#10B981",
    "warning": "#F59E0B",
    "error": "#EF4444",
    "info": "#3B82F6",
}

# Dark theme colors
THEME_COLORS = {
    "background": "#0F172A",
    "background_secondary": "#1E293B",
    "card": "#1E293B",
    "foreground": "#F1F5F9",
    "foreground_muted": "#94A3B8",
    "border": "#334155",
}

# Supported file formats
SUPPORTED_FILE_TYPES = ["csv", "xlsx", "xls"]

# Column type hints for auto-detection
DATE_COLUMN_HINTS = ["date", "week", "month", "day", "time", "period"]
TARGET_COLUMN_HINTS = ["sales", "revenue", "conversions", "kpi", "target", "y"]
SPEND_COLUMN_HINTS = ["spend", "cost", "budget", "investment", "media"]
