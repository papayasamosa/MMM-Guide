"""
Generate a synthetic Family-History (FH) MMM dataset shaped like Ancestry's
actual measurement problem, so the tool can be run and demoed end-to-end
without real Ancestry data.

Structure mirrors what the requirements brief asks the ingestion layer to
support: separate media / outcomes / controls files, joined on date + market,
with three FH segments (New, DNA cross-sell, Winback) and a DNA halo pathway.

Not a calibrated model of Ancestry's real business - it exists to exercise
the pipeline (adstock, saturation, hierarchy, DNA halo, promo-by-segment)
with signal that a correctly-specified model should be able to recover.

Run: uv run python ancestry_mmm/sample_data/generate_sample_data.py
"""

import numpy as np
import pandas as pd
from pathlib import Path

OUT_DIR = Path(__file__).parent
rng = np.random.default_rng(7)

MARKETS = {
    # market: (n_weeks, start_date, maturity_scale)
    "UK": (156, "2023-01-02", 1.00),
    "Australia": (104, "2024-01-01", 0.55),
    "Canada": (104, "2024-01-01", 0.45),
}

CHANNELS = [
    "TV_Brand", "TV_DR", "Search_Brand", "Search_NonBrand",
    "Social", "Direct_Mail", "DNA_Media",
]

# Adstock decay (carryover) and Hill saturation params used to *simulate*
# the "true" shared curves the model should be able to recover.
TRUE_ADSTOCK = {
    "TV_Brand": 0.75, "TV_DR": 0.55, "Search_Brand": 0.20, "Search_NonBrand": 0.30,
    "Social": 0.35, "Direct_Mail": 0.45, "DNA_Media": 0.60,
}
TRUE_HILL_K = {  # half-saturation point, in weekly spend units (scaled per market below)
    "TV_Brand": 45000, "TV_DR": 30000, "Search_Brand": 8000, "Search_NonBrand": 15000,
    "Social": 12000, "Direct_Mail": 10000, "DNA_Media": 20000,
}
TRUE_HILL_S = {
    "TV_Brand": 1.3, "TV_DR": 1.1, "Search_Brand": 0.9, "Search_NonBrand": 1.0,
    "Social": 1.0, "Direct_Mail": 1.1, "DNA_Media": 1.2,
}

# Segment-specific response multipliers relative to the shared curve (the
# "partial pooling" target the hierarchical model should recover).
SEGMENT_MULT = {
    "New":            {"TV_Brand": 1.00, "TV_DR": 1.00, "Search_Brand": 0.70, "Search_NonBrand": 1.00, "Social": 1.00, "Direct_Mail": 0.60, "DNA_Media": 0.15},
    "DNA_CrossSell":  {"TV_Brand": 0.30, "TV_DR": 0.25, "Search_Brand": 0.55, "Search_NonBrand": 0.35, "Social": 0.45, "Direct_Mail": 0.40, "DNA_Media": 1.00},
    "Winback":        {"TV_Brand": 0.35, "TV_DR": 0.45, "Search_Brand": 0.60, "Search_NonBrand": 0.40, "Social": 0.30, "Direct_Mail": 0.75, "DNA_Media": 0.10},
}

# DNA halo: DNA media also lifts the *New* segment a little (people see DNA
# ads, join Ancestry generally) - this is the "smaller effect elsewhere"
# pathway the brief calls out.
DNA_HALO_ON_NEW = 0.15

# Segment promo sensitivity (Winback should be the most promo-responsive).
PROMO_SENSITIVITY = {"New": 0.08, "DNA_CrossSell": 0.10, "Winback": 0.35}

# Segment LTV (£, relative) used later for LTV-weighted optimisation.
SEGMENT_LTV = {"New": 180, "DNA_CrossSell": 260, "Winback": 110}

BASELINE_GSA = {"New": 3200, "DNA_CrossSell": 900, "Winback": 700}

# --- DNA kit purchase outcomes (distinct from the FH "DNA cross-sell" GSA
# above, which is a Family History sign-up event - these are DNA kit sale
# events: PR2 of the DNA/FH architecture work, see docs/outcomes.md).
# "New" = a customer with no prior Family History engagement buying a DNA
# kit; "Existing FH" = an existing Family History customer buying one as a
# cross-sell/add-on. Kept as two separate synthetic series (rather than
# generating a combined-only demo) so the demo project can exercise the
# split-outcome path through core.outcomes, not only the single-column
# fallback.
DNA_KIT_BASELINE = {"New Customer": 800, "Existing FH Customer": 250}
# DNA media response: kit purchases from new customers respond strongly to
# DNA-targeted media (that's what it's built to sell); existing customers
# are already engaged and respond more weakly to media, more to promo/price.
DNA_KIT_MEDIA_MULT = {"New Customer": 1.20, "Existing FH Customer": 0.40}
DNA_KIT_PROMO_SENSITIVITY = {"New Customer": 0.20, "Existing FH Customer": 0.30}
# Kit purchases are more price-sensitive than the FH DNA-cross-sell signup
# metric above (-0.006) - a kit purchase is the actual transaction, not just
# an expression of interest.
DNA_KIT_PRICE_COEF = -0.010
# DNA kits are a classic gift item - lean harder into the Christmas/New
# Year seasonality spike than the FH outcomes do.
DNA_KIT_SEASONALITY_WEIGHT = 0.8
DNA_KIT_LTV = {"New Customer": 90, "Existing FH Customer": 65}


def geometric_adstock(x, decay):
    out = np.zeros_like(x)
    out[0] = x[0]
    for t in range(1, len(x)):
        out[t] = x[t] + decay * out[t - 1]
    return out


def hill(x, k, s):
    x = np.clip(x, 0, None)
    return x ** s / (k ** s + x ** s)


def gifting_seasonality(dates: pd.DatetimeIndex) -> np.ndarray:
    """Christmas/New Year DNA gifting spike, Mother's/Father's Day, DNA Day, WDYTYA airing."""
    week_of_year = dates.isocalendar().week.to_numpy()
    signal = np.zeros(len(dates))
    signal += 0.9 * np.exp(-0.5 * ((week_of_year - 51) / 1.5) ** 2)   # Christmas gifting
    signal += 0.9 * np.exp(-0.5 * ((week_of_year - 1) / 1.5) ** 2)    # New Year "start my tree"
    signal += 0.35 * np.exp(-0.5 * ((week_of_year - 11) / 1.2) ** 2)  # Mother's Day (UK, approx)
    signal += 0.25 * np.exp(-0.5 * ((week_of_year - 24) / 1.2) ** 2)  # Father's Day (approx)
    signal += 0.30 * np.exp(-0.5 * ((week_of_year - 15) / 1.0) ** 2)  # DNA Day (25 Apr)
    signal += 0.20 * np.exp(-0.5 * ((week_of_year - 40) / 1.5) ** 2)  # WDYTYA autumn TV run
    return signal


def build_market(market: str, n_weeks: int, start_date: str, maturity: float) -> dict:
    dates = pd.date_range(start_date, periods=n_weeks, freq="W-MON")
    seasonality = gifting_seasonality(dates)
    trend = np.linspace(0, 0.15, n_weeks) * maturity  # slow underlying growth

    # --- media spend (weekly), each channel with its own baseline level,
    # some seasonal flighting, and noise. Spend scaled down for smaller markets.
    media = {}
    for ch in CHANNELS:
        base_level = {
            "TV_Brand": 55000, "TV_DR": 35000, "Search_Brand": 12000, "Search_NonBrand": 22000,
            "Social": 18000, "Direct_Mail": 15000, "DNA_Media": 25000,
        }[ch] * maturity
        flight = 0.5 + 0.5 * (0.4 + 0.6 * seasonality / seasonality.max())
        noise = rng.normal(1.0, 0.12, n_weeks).clip(0.5, 1.6)
        spend = base_level * flight * noise
        # occasional zero-spend weeks (flighted channels), except always-on search
        if ch not in ("Search_Brand", "Search_NonBrand"):
            off_weeks = rng.random(n_weeks) < 0.08
            spend[off_weeks] = 0.0
        media[ch] = np.round(spend, 0)

    # --- controls
    dna_kit_price = 79 + 20 * np.sin(np.linspace(0, 6, n_weeks)) + rng.normal(0, 2, n_weeks)
    dna_kit_price = np.round(dna_kit_price.clip(39, 129), 2)
    new_promo = (rng.random(n_weeks) < 0.15).astype(float)
    winback_promo = (rng.random(n_weeks) < 0.20).astype(float)
    dna_promo = ((seasonality > 0.5) | (rng.random(n_weeks) < 0.10)).astype(float)
    consumer_confidence = 100 + 5 * np.sin(np.linspace(0, 4, n_weeks)) + rng.normal(0, 1.5, n_weeks)

    # --- adstock + saturation per channel (shared "true" curve, market-scaled K)
    adstocked = {}
    saturated = {}
    for ch in CHANNELS:
        ad = geometric_adstock(media[ch], TRUE_ADSTOCK[ch])
        adstocked[ch] = ad
        sat = hill(ad, TRUE_HILL_K[ch] * maturity, TRUE_HILL_S[ch])
        saturated[ch] = sat

    outcomes = {}
    for seg in ("New", "DNA_CrossSell", "Winback"):
        media_effect = np.zeros(n_weeks)
        for ch in CHANNELS:
            media_effect += SEGMENT_MULT[seg][ch] * saturated[ch]

        if seg == "New":
            media_effect += DNA_HALO_ON_NEW * saturated["DNA_Media"]

        promo_flag = {"New": new_promo, "DNA_CrossSell": dna_promo, "Winback": winback_promo}[seg]
        promo_lift = 1 + PROMO_SENSITIVITY[seg] * promo_flag

        price_effect = 1.0
        if seg == "DNA_CrossSell":
            price_effect = 1 - 0.006 * (dna_kit_price - dna_kit_price.mean())

        baseline = BASELINE_GSA[seg] * maturity * (1 + trend) * (1 + 0.5 * seasonality if seg == "DNA_CrossSell" else 1 + 0.15 * seasonality)
        mean_gsa = baseline * (1 + media_effect) * promo_lift * price_effect
        mean_gsa = np.clip(mean_gsa, 5, None)

        # Negative-binomial-like overdispersed count noise
        dispersion = 25.0
        p = dispersion / (dispersion + mean_gsa)
        gsa = rng.negative_binomial(dispersion, p)
        outcomes[seg] = gsa

    # --- DNA kit purchase outcomes (separate business events from the FH
    # DNA-cross-sell GSA above - see the DNA_KIT_* constants' docstring).
    dna_kit_outcomes = {}
    for dna_seg in ("New Customer", "Existing FH Customer"):
        media_effect = DNA_KIT_MEDIA_MULT[dna_seg] * saturated["DNA_Media"]
        promo_lift = 1 + DNA_KIT_PROMO_SENSITIVITY[dna_seg] * dna_promo
        price_effect = 1 + DNA_KIT_PRICE_COEF * (dna_kit_price - dna_kit_price.mean())
        baseline = DNA_KIT_BASELINE[dna_seg] * maturity * (1 + trend) * (1 + DNA_KIT_SEASONALITY_WEIGHT * seasonality)
        mean_kits = np.clip(baseline * (1 + media_effect) * promo_lift * price_effect, 5, None)

        dispersion = 20.0
        p = dispersion / (dispersion + mean_kits)
        dna_kit_outcomes[dna_seg] = rng.negative_binomial(dispersion, p)

    media_df = pd.DataFrame({"date": dates, "market": market, **media})
    outcomes_df = pd.DataFrame({
        "date": dates, "market": market,
        "GSA_New": outcomes["New"],
        "GSA_DNA_CrossSell": outcomes["DNA_CrossSell"],
        "GSA_Winback": outcomes["Winback"],
        "DNA_Kit_New_Customer": dna_kit_outcomes["New Customer"],
        "DNA_Kit_Existing_FH_Customer": dna_kit_outcomes["Existing FH Customer"],
    })
    controls_df = pd.DataFrame({
        "date": dates, "market": market,
        "DNA_Kit_Price": dna_kit_price,
        "Promo_New": new_promo,
        "Promo_DNA": dna_promo,
        "Promo_Winback": winback_promo,
        "Consumer_Confidence": np.round(consumer_confidence, 1),
    })
    return {"media": media_df, "outcomes": outcomes_df, "controls": controls_df}


def main():
    media_parts, outcomes_parts, controls_parts = [], [], []
    for market, (n_weeks, start, maturity) in MARKETS.items():
        parts = build_market(market, n_weeks, start, maturity)
        media_parts.append(parts["media"])
        outcomes_parts.append(parts["outcomes"])
        controls_parts.append(parts["controls"])

    media_df = pd.concat(media_parts, ignore_index=True)
    outcomes_df = pd.concat(outcomes_parts, ignore_index=True)
    controls_df = pd.concat(controls_parts, ignore_index=True)

    media_df.to_csv(OUT_DIR / "ancestry_media_sample.csv", index=False)
    outcomes_df.to_csv(OUT_DIR / "ancestry_outcomes_sample.csv", index=False)
    controls_df.to_csv(OUT_DIR / "ancestry_controls_sample.csv", index=False)

    ltv_df = pd.DataFrame(
        [{"segment": seg, "ltv": val} for seg, val in SEGMENT_LTV.items()]
    )
    ltv_df.to_csv(OUT_DIR / "ancestry_segment_ltv_sample.csv", index=False)

    print(f"media:    {media_df.shape}")
    print(f"outcomes: {outcomes_df.shape}")
    print(f"controls: {controls_df.shape}")
    print(f"ltv:      {ltv_df.shape}")


if __name__ == "__main__":
    main()
