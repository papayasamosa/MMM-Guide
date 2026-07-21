"""
Model comparison workflow (docs/model_validation.md): compare Model A (one
shared curve), Model B (independent per-market models), and Model C
(partially pooled, market-specific curves) before adopting a market-specific
model as the default.

Model B needs no new model-building code: an "independent per-market model"
is exactly `core.hierarchical_model.build_fh_hierarchical_model` (Model A's
builder) fit against a single-market slice of the frame - partial pooling
across markets is meaningless with only one market in scope, which is
precisely what "independent" means. `slice_frame_to_market` below produces
that single-market frame; the existing Structure page's market selection
already lets a user do this from the UI without any new page, by fitting
Model A after selecting just one market.

This module keeps the *comparison bookkeeping* - a candidate record per
fitted model and a side-by-side table - not the fitting itself, since
fitting a real model is slow (minutes, not seconds) and the app should never
force three sequential fits behind a single blocking button. See
pages/12_Compare_Models.py for how candidates are recorded (one at a time,
user-paced) and displayed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


def slice_frame_to_market(frame: Dict[str, Any], market: str) -> Dict[str, Any]:
    """
    Slice a prepared modelling frame (data.preprocessor.prepare_fh_modeling_frame
    output) down to one market's rows, for an independent single-market fit
    (Model B). The result is a valid frame in its own right - markets=[market],
    a single (0, n) market_bounds block - so it can be passed straight to
    `core.hierarchical_model.build_fh_hierarchical_model` unchanged.
    """
    if market not in frame["markets"]:
        raise ValueError(f"'{market}' is not one of this frame's markets: {frame['markets']}")

    idx = frame["markets"].index(market)
    start, end = frame["market_bounds"][idx]

    sliced = dict(frame)
    sliced["markets"] = [market]
    sliced["market_idx"] = np.zeros(end - start, dtype=int)
    sliced["market_bounds"] = [(0, end - start)]
    sliced["unpooled_markets"] = []  # a single market has nothing to pool with or opt out of

    for key in ("X_media", "Y", "promo", "X_controls", "fourier", "trend", "dates"):
        sliced[key] = frame[key][start:end]

    sliced["segment_controls"] = {
        seg: arr[start:end] for seg, arr in (frame.get("segment_controls") or {}).items()
    }
    sliced["df"] = frame["df"].iloc[start:end].reset_index(drop=True)

    return sliced


@dataclass
class ModelComparisonCandidate:
    """One fitted model's comparison record - a snapshot of its scorecard,
    not the model/trace itself (those stay wherever the page that fit it put
    them; keeping only the scorecard here keeps this list small and
    JSON-serialisable for session state / persistence)."""

    model_type: str            # "A" (shared), "B" (independent per-market), "C" (partially pooled)
    label: str                 # user-facing label, e.g. "Model A - shared curve" or "Model B - UK only"
    model_run_id: str
    fitted_at: float
    market: Optional[str] = None       # set for Model B candidates (which market)
    convergence: Dict[str, Any] = field(default_factory=dict)
    in_sample_fit: list = field(default_factory=list)   # list of {segment, r_squared, mape_pct, ...}
    ppc_coverage: list = field(default_factory=list)
    n_plausibility_flags: int = 0

    def to_dict(self) -> dict:
        return {
            "model_type": self.model_type, "label": self.label, "model_run_id": self.model_run_id,
            "fitted_at": self.fitted_at, "market": self.market, "convergence": self.convergence,
            "in_sample_fit": self.in_sample_fit, "ppc_coverage": self.ppc_coverage,
            "n_plausibility_flags": self.n_plausibility_flags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ModelComparisonCandidate":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_scorecard(
        cls, *, model_type: str, label: str, model_run_id: str, fitted_at: float,
        scorecard: Dict[str, Any], market: Optional[str] = None,
    ) -> "ModelComparisonCandidate":
        return cls(
            model_type=model_type, label=label, model_run_id=model_run_id, fitted_at=fitted_at,
            market=market, convergence=scorecard.get("convergence", {}),
            in_sample_fit=scorecard.get("in_sample_fit", []),
            ppc_coverage=scorecard.get("ppc_coverage", []),
            n_plausibility_flags=len(scorecard.get("plausibility_flags", [])),
        )


def candidates_to_dataframe(candidates: list) -> pd.DataFrame:
    """Side-by-side comparison table: one row per candidate, with mean
    in-sample R-squared/MAPE and mean PPC coverage collapsed across segments
    so different candidates (which may cover different segment/market
    combinations) are still comparable at a glance. Per-segment detail
    remains available on each ModelComparisonCandidate itself."""
    rows = []
    for c in candidates:
        r2_vals = [r["r_squared"] for r in c.in_sample_fit if r.get("r_squared") is not None]
        mape_vals = [r["mape_pct"] for r in c.in_sample_fit if r.get("mape_pct") is not None]
        cov_vals = [r["coverage_pct"] for r in c.ppc_coverage if r.get("coverage_pct") is not None]
        rows.append({
            "label": c.label,
            "model_type": c.model_type,
            "market": c.market or "(all)",
            "rhat_max": c.convergence.get("rhat_max"),
            "ess_min": c.convergence.get("ess_min"),
            "divergences": c.convergence.get("divergences"),
            "converged": c.convergence.get("converged"),
            "mean_r_squared": float(np.mean(r2_vals)) if r2_vals else None,
            "mean_mape_pct": float(np.mean(mape_vals)) if mape_vals else None,
            "mean_ppc_coverage_pct": float(np.mean(cov_vals)) if cov_vals else None,
            "plausibility_flags": c.n_plausibility_flags,
        })
    return pd.DataFrame(rows)
