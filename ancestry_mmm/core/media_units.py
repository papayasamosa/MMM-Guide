"""
CPA and media-unit/inflation calculations - Phase 3b of the market-specific
redesign (docs/media_units_and_inflation.md).

Deliberately decoupled from any particular model's posterior-parameter
shape: everything here operates on a *curve DataFrame* - the common column
shape both `core.predict.generate_channel_curve` (Model A) and
`core.market_specific_predict.generate_market_channel_curve` (Model C)
already produce (`spend`, `saturation`, `{segment}_response...`,
`overall_response`) - so CPA and media-unit conversion work identically for
either model type without branching here on which one produced the curve.

Point estimates only, same convention as the curve generators themselves.
Credible intervals on CPA (which would need per-draw curve generation, not
just posterior means) are an explicit, documented next step - see
docs/decision_log.md - not attempted here. `cpa_stability_flags` below is a
point-estimate proxy for "this part of the curve is too flat to trust a
marginal CPA number from," not a substitute for real posterior uncertainty.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .hierarchical_model import FHModelMeta
from .market_config import ChannelMediaUnitConfig
from .market_specific_predict import FHMarketSpecificPosteriorParams, generate_market_channel_curve


def compute_cpa(
    curve_df: pd.DataFrame, response_col: str = "overall_response", *, allow_mixed: bool = False, column_prefix: str = "",
) -> pd.DataFrame:
    """
    Add `avg_cpa` and `marginal_cpa` columns to a spend -> response curve
    DataFrame:

        Average CPA  = Spend / Incremental outcomes
        Marginal CPA = Change in spend / Change in incremental outcomes

    Both reported together (they diverge meaningfully near saturation).
    Never computed (left NaN) where response, or the change in response
    between consecutive curve points, is zero or negative -
    docs/media_units_and_inflation.md is explicit that CPA on a
    zero-or-negative-response base is meaningless, not just large.

    `response_col` must identify what's being counted in the denominator
    (the instruction document's explicit requirement - "CPA must identify
    its denominator... never calculate total spend divided by FH GSAs plus
    DNA kits and call it simply CPA"). Defaults to `"overall_response"` for
    backward compatibility with curves that only ever have one product (the
    overwhelming majority - a project with no DNA-kit segments has
    `dna_response` identically zero, so `overall_response == fh_response`
    and there's nothing to disambiguate). If the curve genuinely mixes both
    (`fh_response` and `dna_response` both present and non-trivial) and the
    caller asks for `"overall_response"` without acknowledging that, this
    raises rather than silently dividing spend by a sum of two different
    units - pass `response_col="fh_response"` or `"dna_response"`
    explicitly, or `allow_mixed=True` to acknowledge a deliberately mixed
    denominator. `column_prefix` names the output columns
    `{prefix}avg_cpa`/`{prefix}marginal_cpa` instead of the bare names, so
    a caller computing CPA against more than one `response_col` on the same
    curve (see `compute_cpa_by_product`) doesn't collide column names.
    """
    if response_col == "overall_response" and not allow_mixed:
        has_fh = "fh_response" in curve_df.columns and (curve_df["fh_response"] > 0).any()
        has_dna = "dna_response" in curve_df.columns and (curve_df["dna_response"] > 0).any()
        if has_fh and has_dna:
            raise ValueError(
                "This curve mixes Family History GSAs and DNA kit sales - computing CPA against "
                "'overall_response' would divide spend by a sum of two different units. Pass "
                "response_col='fh_response' or response_col='dna_response' explicitly (or "
                "allow_mixed=True to acknowledge a deliberately mixed denominator)."
            )

    out = curve_df.copy()
    spend = out["spend"].to_numpy()
    response = out[response_col].to_numpy()

    avg_cpa = np.where(response > 0, spend / np.where(response > 0, response, np.nan), np.nan)

    marginal_cpa = np.full(len(out), np.nan)
    if len(out) > 1:
        d_spend = np.diff(spend)
        d_response = np.diff(response)
        positive = d_response > 0
        marginal_cpa[1:][positive] = d_spend[positive] / d_response[positive]

    out[f"{column_prefix}avg_cpa"] = avg_cpa
    out[f"{column_prefix}marginal_cpa"] = marginal_cpa
    return out


# ---------------------------------------------------------------------------
# CPA denominator/spend-scope metadata (PR E.2 requirement #8)
#
# Confirmed pitfall: scenario-level "cost per GSA" divides total scenario
# spend (every channel) by a KPI total, which is a legitimate whole-plan
# efficiency measure but is NOT the same thing as a channel-specific curve's
# own CPA, an incremental-effect CPA, or an agency/platform-reported CPA
# computed directly from observed data (not modelled at all). Every CPA
# number in this codebase must be presentable with this metadata attached -
# never a bare `avg_cpa` with no visible scope.
# ---------------------------------------------------------------------------

CPA_SPEND_SCOPES = ("whole_plan", "channel_incremental", "observed_platform")
CPA_INCREMENTAL_VS_OBSERVED = ("incremental", "observed")


def cpa_scope_metadata(
    *,
    denominator_metric: str,
    included_outcome_ids: List[str],
    spend_scope: str,
    included_channels: Optional[List[str]] = None,
    market: Optional[str] = None,
    time_window: Optional[str] = None,
    incremental_vs_observed: str = "incremental",
) -> Dict[str, object]:
    """
    The required metadata contract for a CPA number (PR E.2 #8): what it
    divides by (`denominator_metric`/`included_outcome_ids`), what spend
    it's computed over (`spend_scope`/`included_channels`), which
    `market`/`time_window` it applies to, and whether it's a modelled
    incremental effect or a directly observed/reported number
    (`incremental_vs_observed`). A UI/export showing a CPA number without
    this metadata visible alongside it is the confirmed defect this closes -
    every CPA-producing function in this module returns (or can be paired
    with) this.

    `spend_scope` must be one of `CPA_SPEND_SCOPES`:
    - `"whole_plan"` - total spend across every channel in a scenario,
      divided by that scenario's total for one KPI (e.g.
      `whole_plan_cost_per_fh_gsa` - `core.optimization.evaluate_scenario`'s
      `avg_cpa`/`cost_per_fh_gsa`). A genuine whole-plan efficiency number,
      not a channel-specific one.
    - `"channel_incremental"` - one channel's own response curve at a given
      spend level, holding other channels fixed (e.g.
      `channel_incremental_cost_per_fh_gsa` -
      `compute_cpa_by_product`'s `avg_cpa`/`cost_per_fh_gsa`). Not the same
      number as the whole-plan CPA even when only one channel is active.
    - `"observed_platform"` - directly observed/reported spend and
      conversions (e.g. ad-platform-reported CPA), no model involved at
      all. **Not computed anywhere in this codebase yet** (no per-channel
      platform-reported conversion data is captured) - a documented future
      extension, not a promise this function fulfils; `incremental_vs_
      observed="observed"` is reserved for when it is.
    """
    if spend_scope not in CPA_SPEND_SCOPES:
        raise ValueError(f"spend_scope must be one of {CPA_SPEND_SCOPES}, got {spend_scope!r}.")
    if incremental_vs_observed not in CPA_INCREMENTAL_VS_OBSERVED:
        raise ValueError(
            f"incremental_vs_observed must be one of {CPA_INCREMENTAL_VS_OBSERVED}, got "
            f"{incremental_vs_observed!r}."
        )
    return {
        "denominator_metric": denominator_metric,
        "included_outcome_ids": list(included_outcome_ids),
        "spend_scope": spend_scope,
        "included_channels": list(included_channels) if included_channels is not None else None,
        "market": market,
        "time_window": time_window,
        "incremental_vs_observed": incremental_vs_observed,
    }


def compute_cpa_by_product(curve_df: pd.DataFrame) -> pd.DataFrame:
    """
    Metric-aware CPA (PR E.1): computes `avg_cpa`/`marginal_cpa` (aliases
    `cost_per_fh_gsa`/`fh_gsa_marginal_cpa`) against `fh_response` (Family
    History GSA outcomes, `core.outcomes.fh_gsa_outcome_ids` - a sign-up
    outcome on the same segment is never included), and - only where the
    curve actually has a non-trivial `dna_response`/`fh_signup_response` (a
    DNA-kit outcome, or a distinct sign-up outcome, fit alongside it) -
    *additionally* `dna_avg_cpa`/`dna_marginal_cpa` (alias
    `cost_per_dna_kit`) against `dna_response`, and `fh_signup_avg_cpa`/
    `fh_signup_marginal_cpa` (alias `cost_per_fh_signup`) against
    `fh_signup_response`, prefixed so no denominator is silently mixed into
    another (the instruction document's "CPA must identify its
    denominator" requirement).

    The overwhelming majority of curves (no DNA-kit outcomes, no distinct
    sign-up outcome) get exactly the same `avg_cpa`/`marginal_cpa` columns
    as before, with the same values (`fh_response == overall_response` when
    `dna_response`/`fh_signup_response` are identically zero) - this is the
    safe default entry point for UI/export code that used to call
    `compute_cpa(curve_df)` with no `response_col`, which would now raise on
    a genuinely mixed curve instead of silently mixing units.
    """
    if "fh_response" not in curve_df.columns:
        # Curve predates the fh_response/dna_response split (shouldn't
        # happen from this codebase's own generators, but defensive against
        # any external/hand-built curve) - fall back to the legacy,
        # single-denominator behaviour rather than erroring.
        return compute_cpa(curve_df, "overall_response", allow_mixed=True)

    out = compute_cpa(curve_df, "fh_response", allow_mixed=True)
    out["cost_per_fh_gsa"] = out["avg_cpa"]
    out["fh_gsa_marginal_cpa"] = out["marginal_cpa"]
    # `channel_incremental_*` (PR E.2 #8) - the explicit-spend-scope name for
    # exactly the same numbers: this curve is one channel's own response at
    # varying spend, holding other channels fixed, so `avg_cpa`/`marginal_cpa`
    # here are channel-incremental, never a whole-plan number. The bare
    # `avg_cpa`/`cost_per_fh_gsa` names are kept as legacy aliases.
    out["channel_incremental_cost_per_fh_gsa"] = out["avg_cpa"]
    out["channel_incremental_marginal_cost_per_fh_gsa"] = out["marginal_cpa"]
    if (
        "fh_net_billthrough_response" in curve_df.columns
        and (curve_df["fh_net_billthrough_response"] > 0).any()
    ):
        nbt = compute_cpa(
            curve_df, "fh_net_billthrough_response", allow_mixed=True,
            column_prefix="fh_net_billthrough_",
        )
        out["channel_incremental_cost_per_fh_net_billthrough"] = nbt["fh_net_billthrough_avg_cpa"]
        out["channel_incremental_marginal_cost_per_fh_net_billthrough"] = nbt["fh_net_billthrough_marginal_cpa"]
    has_dna = "dna_response" in curve_df.columns and (curve_df["dna_response"] > 0).any()
    if has_dna:
        dna_cpa = compute_cpa(curve_df, "dna_response", allow_mixed=True, column_prefix="dna_")
        out["dna_avg_cpa"] = dna_cpa["dna_avg_cpa"]
        out["dna_marginal_cpa"] = dna_cpa["dna_marginal_cpa"]
        out["cost_per_dna_kit"] = dna_cpa["dna_avg_cpa"]
        out["channel_incremental_cost_per_dna_kit"] = dna_cpa["dna_avg_cpa"]
        out["channel_incremental_marginal_cost_per_dna_kit"] = dna_cpa["dna_marginal_cpa"]
    has_signup = "fh_signup_response" in curve_df.columns and (curve_df["fh_signup_response"] > 0).any()
    if has_signup:
        signup_cpa = compute_cpa(curve_df, "fh_signup_response", allow_mixed=True, column_prefix="fh_signup_")
        out["fh_signup_avg_cpa"] = signup_cpa["fh_signup_avg_cpa"]
        out["fh_signup_marginal_cpa"] = signup_cpa["fh_signup_marginal_cpa"]
        out["cost_per_fh_signup"] = signup_cpa["fh_signup_avg_cpa"]
        out["channel_incremental_cost_per_fh_signup"] = signup_cpa["fh_signup_avg_cpa"]
        out["channel_incremental_marginal_cost_per_fh_signup"] = signup_cpa["fh_signup_marginal_cpa"]
    return out


def cpa_stability_flags(
    curve_df: pd.DataFrame, response_col: str = "overall_response", relative_threshold: float = 0.02,
) -> List[Dict[str, object]]:
    """
    Flag curve points where the response is so flat (near-saturated, or
    near-zero spend before response has picked up) that a small change in
    the fitted curve would swing marginal CPA by a large amount - a
    point-estimate proxy for "posterior uncertainty makes CPA unstable here"
    (see module docstring for why this isn't full credible-interval-based
    instability detection).

    Unlike `compute_cpa`/`equivalent_response`, this does not gate on
    `response_col="overall_response"` mixing FH GSAs and DNA kits: it
    returns advisory flags about curve shape, not a dollar-denominated
    number, so a mixed-unit `overall_response` at worst flags the wrong
    spend points rather than misreporting a CPA. Known residual gap, not
    fixed here - pass `response_col="fh_response"`/`"dna_response"`
    explicitly on a curve with DNA-kit segments if precise flagging matters.
    """
    response = curve_df[response_col].to_numpy()
    if len(response) < 2:
        return []
    d_response = np.diff(response)
    max_d = float(np.max(np.abs(d_response))) if len(d_response) else 0.0
    if max_d <= 0:
        return []

    flags = []
    for i, dr in enumerate(d_response, start=1):
        if abs(dr) < relative_threshold * max_d:
            flags.append({
                "index": i,
                "spend": float(curve_df["spend"].iloc[i]),
                "message": (
                    f"Marginal response near spend={curve_df['spend'].iloc[i]:,.0f} is very flat "
                    "relative to the rest of this curve - marginal CPA here is highly sensitive to "
                    "small changes in the fitted curve; treat with caution."
                ),
            })
    return flags


def extract_cost_per_unit_series(
    df: pd.DataFrame,
    date_col: str,
    market_col: str,
    market: str,
    config: ChannelMediaUnitConfig,
) -> pd.DataFrame:
    """
    Historical `cost_per_unit = spend / media_units` by date for one
    (market, channel), from the raw transformed data - the "historical cost
    relationship" docs/media_units_and_inflation.md describes. Requires
    `config.has_media_unit()` (a spend-only channel has no delivery column
    to divide by).
    """
    if not config.has_media_unit():
        raise ValueError(
            f"No response-unit column mapped for {config.market}/{config.channel} - "
            "this channel is spend-only, there's no cost-per-unit relationship to extract."
        )
    missing = [c for c in (config.spend_column, config.response_unit_column) if c not in df.columns]
    if missing:
        raise ValueError(f"Column(s) missing from data: {missing}")

    mask = df[market_col] == market
    sub = df.loc[mask, [date_col, config.spend_column, config.response_unit_column]].copy()
    sub = sub.rename(columns={config.spend_column: "spend", config.response_unit_column: "media_units"})
    sub["cost_per_unit"] = np.where(
        sub["media_units"] > 0, sub["spend"] / sub["media_units"], np.nan,
    )
    return sub.sort_values(date_col).reset_index(drop=True)


def historical_cost_trend(
    cost_series_df: pd.DataFrame, date_col: str, cost_col: str = "cost_per_unit",
) -> Dict[str, object]:
    """
    Year-on-year inflation rate and an indexed cost trend (base = 100 at the
    first year with data), from a per-date cost-per-unit series (typically
    `extract_cost_per_unit_series`'s output). Nominal vs. inflation-adjusted
    spend both fall out of this: `indexed_trend` shows the nominal
    `cost_per_unit` alongside its index, so a caller can deflate any nominal
    spend figure by dividing out the index for its year.
    """
    valid = cost_series_df.dropna(subset=[cost_col]).copy()
    if valid.empty:
        return {"yoy_inflation_pct": None, "indexed_trend": pd.DataFrame(columns=["year", cost_col, "indexed"]), "avg_cost_per_unit": None}

    valid["year"] = pd.to_datetime(valid[date_col]).dt.year
    annual = valid.groupby("year", as_index=False)[cost_col].mean().sort_values("year")
    base = float(annual[cost_col].iloc[0])
    annual["indexed"] = (annual[cost_col] / base) * 100.0 if base > 0 else np.nan

    yoy_inflation_pct = None
    if len(annual) >= 2:
        first, last = float(annual[cost_col].iloc[0]), float(annual[cost_col].iloc[-1])
        n_years = int(annual["year"].iloc[-1] - annual["year"].iloc[0])
        if n_years > 0 and first > 0:
            yoy_inflation_pct = ((last / first) ** (1.0 / n_years) - 1.0) * 100.0

    return {
        "yoy_inflation_pct": yoy_inflation_pct,
        "indexed_trend": annual.reset_index(drop=True),
        "avg_cost_per_unit": float(valid[cost_col].mean()),
    }


def response_unit_curve(curve_df: pd.DataFrame, avg_cost_per_unit: float) -> pd.DataFrame:
    """
    Convert a spend -> response curve into a media-units -> response curve
    by dividing the spend axis by `avg_cost_per_unit` (typically
    `historical_cost_trend(...)["avg_cost_per_unit"]`).

    This is an explicit simplification, documented here rather than hidden:
    it assumes a single, constant cost-per-unit across the whole curve's
    spend range, so the media-unit axis is a linear rescaling of the spend
    axis rather than an independently-observed spend-to-delivery
    relationship at every spend level. A time-varying or spend-level-varying
    cost-per-unit model is a documented future extension - see
    docs/decision_log.md.
    """
    if avg_cost_per_unit <= 0:
        raise ValueError(f"avg_cost_per_unit must be positive, got {avg_cost_per_unit}")
    out = curve_df.copy()
    out["media_units"] = out["spend"] / avg_cost_per_unit
    return out


def equivalent_delivery(target_media_units: float, expected_future_cost_per_unit: float) -> float:
    """
    "How much would I need to spend to buy this many media units, at an
    assumed future cost per unit?" - `required_spend = target_media_units x
    expected_future_cost_per_unit`. The cost assumption is always an
    explicit argument, never inferred silently - docs/media_units_and_inflation.md's
    "a future inflation assumption is never applied silently" rule.
    """
    if target_media_units < 0 or expected_future_cost_per_unit < 0:
        raise ValueError("target_media_units and expected_future_cost_per_unit must be non-negative")
    return target_media_units * expected_future_cost_per_unit


def equivalent_response(
    target_media_units: float,
    cost_per_unit: float,
    curve_df: pd.DataFrame,
    response_col: str = "overall_response",
    *,
    allow_mixed: bool = False,
) -> float:
    """
    "How many media units are required to produce a given modelled
    response?" solved the other way round: interpolates `curve_df`'s
    response at the spend level equivalent to buying `target_media_units`
    (`target_media_units x cost_per_unit`). Uses the curve's own spend/
    response grid via linear interpolation - no re-derivation of the Hill
    curve's math here, so this works identically for a Model A or Model C
    curve DataFrame.

    Same mixed-denominator guard as `compute_cpa`: this returns a single
    response number, so a caller taking the `"overall_response"` default on
    a curve that mixes FH GSAs and DNA kits would silently get a sum of two
    different units. Pass `response_col="fh_response"` or
    `"dna_response"` explicitly, or `allow_mixed=True` to acknowledge a
    deliberately mixed total.
    """
    if target_media_units < 0 or cost_per_unit < 0:
        raise ValueError("target_media_units and cost_per_unit must be non-negative")
    if response_col == "overall_response" and not allow_mixed:
        has_fh = "fh_response" in curve_df.columns and (curve_df["fh_response"] > 0).any()
        has_dna = "dna_response" in curve_df.columns and (curve_df["dna_response"] > 0).any()
        if has_fh and has_dna:
            raise ValueError(
                "This curve mixes Family History GSAs and DNA kit sales - 'overall_response' "
                "would sum two different units. Pass response_col='fh_response' or "
                "response_col='dna_response' explicitly (or allow_mixed=True)."
            )
    target_spend = target_media_units * cost_per_unit
    spend = curve_df["spend"].to_numpy()
    response = curve_df[response_col].to_numpy()
    return float(np.interp(target_spend, spend, response))


def market_specific_cpa_table(
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    markets: Optional[List[str]] = None,
    channels: Optional[List[str]] = None,
    n_points: int = 10,
) -> pd.DataFrame:
    """
    CPA (average + marginal) for every (market, channel) - one flattened
    table, generated by calling `generate_market_channel_curve` +
    `compute_cpa_by_product` per combination (product-aware: a DNA-targeted
    channel with a mapped DNA-kit segment gets both `avg_cpa` against FH
    GSAs and `dna_avg_cpa` against DNA kits, never one mixed number). Used
    where a single summary sheet/table across every market and channel is
    wanted (e.g. Model C's Excel export, pages/09_Project_Export.py) rather
    than one curve at a time in the interactive viewer.

    `n_points` defaults lower than the interactive viewer's (25) since this
    produces `len(markets) x len(channels) x n_points` rows in one table.
    """
    markets = markets if markets is not None else list(params.hill_K.keys())
    channels = channels if channels is not None else meta.channels

    rows = []
    for market in markets:
        for channel in channels:
            curve_df = generate_market_channel_curve(market, channel, meta, params, n_points=n_points)
            cpa_df = compute_cpa_by_product(curve_df)
            rows.append(cpa_df)
    if not rows:
        return pd.DataFrame(columns=[
            "market", "channel", "spend", "saturation", "overall_response", "fh_response",
            "fh_signup_response", "dna_response",
            "avg_cpa", "marginal_cpa", "cost_per_fh_gsa", "fh_gsa_marginal_cpa",
            "channel_incremental_cost_per_fh_gsa", "channel_incremental_marginal_cost_per_fh_gsa",
            "dna_avg_cpa", "dna_marginal_cpa", "cost_per_dna_kit",
            "channel_incremental_cost_per_dna_kit", "channel_incremental_marginal_cost_per_dna_kit",
            "fh_signup_avg_cpa", "fh_signup_marginal_cpa", "cost_per_fh_signup",
            "channel_incremental_cost_per_fh_signup", "channel_incremental_marginal_cost_per_fh_signup",
        ])
    return pd.concat(rows, ignore_index=True)
