"""WP2.6 items 1 and 2 (analyst-directed, 2026-08-24): identify the
control(s) responsible for the WP2.5 prior-predictive `eta_controls`
finding, and run a bounded `control_sigma` prior-sensitivity grid using
the existing governed control-standardisation mechanism
(`core.control_scaling`, `prior_config["enable_control_scaling"]`).

Reuses `scripts/run_uk_production_fit.py`'s governed data pipeline (via
its `frame_callback` extension point) and `core.diagnostics.
prior_predictive_summary`'s `component_var_names` support (WP2.5) - no
new production code path. Every model rebuild below is prior-predictive
sampling only (no NUTS/MCMC, no observed data read by the sampler).

The analyst's approval covers *direction* only ("continuous model
controls should use a governed standardised representation, with the
coefficient prior explicitly calibrated") - it is not approval of an
exact `control_sigma` and not permission to start WP3. This script does
not select a value; it reports a grid for the analyst to choose from.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pymc as pm

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.application.model_fit_service import build_model_for_spec  # noqa: E402
from ancestry_mmm.core.diagnostics import prior_predictive_summary  # noqa: E402
from ancestry_mmm.core.schema import ModelSpec  # noqa: E402

DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-6-control-prior-20260824"
)

# "A small documented grid... including the current 0.5 for comparison."
# Spans a materially tighter prior (implying a modest effect per one-SD
# control movement) through the current default up to a deliberately wide
# point, so the analyst can see the full range of implied geometry rather
# than a narrow neighbourhood around 0.5.
CONTROL_SIGMA_GRID = [0.05, 0.1, 0.2, 0.3, 0.5, 1.0]

COMPONENT_VAR_NAMES = ["eta_controls", "control_coef", "mu"]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _json_default(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )


def _quantiles(values: np.ndarray) -> dict[str, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {q: float("nan") for q in ("q01", "q05", "q50", "q95", "q99")}
    q01, q05, q50, q95, q99 = np.quantile(finite, [0.01, 0.05, 0.50, 0.95, 0.99])
    return {
        "q01": float(q01),
        "q05": float(q05),
        "q50": float(q50),
        "q95": float(q95),
        "q99": float(q99),
    }


def _control_profile(frame: dict[str, Any]) -> dict[str, Any]:
    """Item 1's descriptive control profile: name, raw scale/range, and a
    type classification derived from the observed values themselves (never
    assumed) - integer-valued with a narrow 0-100-ish range and >2 distinct
    values reads as a continuous/ordinal index; exactly 2 distinct values
    would read as binary/indicator. No control in the real governed UK
    frame is auto-standardised merely because it appears in the control
    block - this classification is what a future column-selective
    standardisation decision would need to consult, and is reported here
    for the analyst's review, not acted on."""
    names = list(frame.get("control_names") or [])
    X = np.asarray(frame["X_controls"], dtype=float)
    profiles = []
    for index, name in enumerate(names):
        column = X[:, index]
        distinct = np.unique(column)
        if distinct.size <= 2 and set(distinct.tolist()).issubset({0.0, 1.0}):
            control_type = "binary_indicator"
        elif np.allclose(column, np.round(column)):
            control_type = "continuous_or_count_index"
        else:
            control_type = "continuous"
        profiles.append(
            {
                "name": name,
                "governed_role": (
                    "context/external-factor control (logical source domain "
                    "context_and_external_factors) - no more specific governed "
                    "type/role record exists for this variable beyond that "
                    "domain classification (checked docs/approved_requirements/ "
                    "and AGENTS.md; no match)"
                ),
                "raw_min": float(column.min()),
                "raw_max": float(column.max()),
                "raw_mean": float(column.mean()),
                "raw_median": float(np.median(column)),
                "raw_std": float(column.std()),
                "n_distinct": int(distinct.size),
                "n_observations": int(column.size),
                "inferred_type": control_type,
            }
        )
    return {"controls": profiles}


def _multiplicative_effect_per_sd(control_coef_draws: np.ndarray) -> dict[str, Any]:
    """Under the standardised representation, one unit of the scaled
    control is exactly one observed standard deviation of the raw control
    (`core.control_scaling.fit_control_scaling`'s `mean_sd` contract). The
    multiplicative effect on the outcome scale of a one-SD control movement
    is therefore `exp(control_coef)` directly - the single most
    interpretable quantity this exercise can hand the analyst, independent
    of the outcome's own count scale."""
    effect = np.exp(control_coef_draws)
    return {
        "interpretation": (
            "multiplicative change in mu for a +1 standard-deviation move "
            "in the (standardised) control; 1.0 = no effect"
        ),
        **_quantiles(effect),
    }


def _pathology_summary(mu_draws: np.ndarray) -> dict[str, Any]:
    finite = mu_draws[np.isfinite(mu_draws)]
    return {
        "n_draws": int(mu_draws.size),
        "n_non_finite": int(mu_draws.size - finite.size),
        "n_clipped_at_floor_1e_minus_6": int(np.sum(finite <= 1e-6 + 1e-12)),
        "n_clipped_at_ceiling_1e9": int(np.sum(finite >= 1e9 - 1.0)),
    }


def _run_one(
    *,
    frame: dict[str, Any],
    spec: ModelSpec,
    model_name: str,
    prior_config: dict[str, Any],
    n_samples: int,
    seed: int,
) -> dict[str, Any]:
    proposed = build_model_for_spec(
        frame=frame,
        model_spec=spec,
        model_type="shared",
        dna_lag_weeks=4,
        dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
        prior_config=prior_config,
        direct_dna_outcome_ids=(
            list(frame["outcome_ids"]) if model_name == "dna_kit" else None
        ),
        causal_graph=None,
        search_objects=(),
    )
    result = prior_predictive_summary(
        proposed.model,
        frame,
        proposed.meta,
        n_samples=n_samples,
        random_seed=seed,
        component_var_names=COMPONENT_VAR_NAMES,
    )
    plausibility = result["plausibility"]
    components = (plausibility.get("component_decomposition") or {}).get(
        "components", {}
    )
    return {
        "prior_config": dict(prior_config),
        "eta_controls": components.get("eta_controls"),
        "control_coef": components.get("control_coef"),
        "mu_component": components.get("mu"),
        "outcome_rows": plausibility["rows"],
    }


def _grid_row_from_run(
    run: dict[str, Any], control_coef_draws: np.ndarray, mu_draws: np.ndarray
) -> dict[str, Any]:
    return {
        "control_sigma": run["prior_config"]["control_sigma"],
        "enable_control_scaling": run["prior_config"]["enable_control_scaling"],
        "multiplicative_effect_per_sd": _multiplicative_effect_per_sd(
            control_coef_draws
        ),
        "eta_controls_quantiles": {
            "q05": run["eta_controls"]["q05"],
            "median": run["eta_controls"]["median"],
            "q95": run["eta_controls"]["q95"],
        }
        if run["eta_controls"]
        else None,
        "mu_pathology": _pathology_summary(mu_draws),
        "outcome_rows": [
            {
                "outcome_id": row["outcome_id"],
                "predictive_quantiles": row["predictive_quantiles"],
                "observed_scale_ratios": row["observed_scale_ratios"],
            }
            for row in run["outcome_rows"]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only-model", choices=["family_history", "dna_kit"])
    parser.add_argument("--n-prior-samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260824)
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    captured: dict[str, tuple[dict[str, Any], ModelSpec]] = {}

    def _capture(model_name: str, frame: dict[str, Any], spec: ModelSpec) -> None:
        captured[model_name] = (frame, spec)

    runner.run(
        pack_dir=args.pack_dir,
        output_dir=args.output_dir / "official_preparation",
        draws=2000,
        tune=1000,
        chains=4,
        target_accept=0.9,
        seed=args.seed,
        fit_enabled=False,
        only_model=args.only_model,
        governed_start=args.governed_start,
        governed_end=args.governed_end,
        prior_config={},
        frame_callback=_capture,
    )

    results: dict[str, Any] = {}
    for model_name, (frame, spec) in captured.items():
        # Item 1: descriptive control profile, then before/after the
        # existing scaling mechanism at the current default control_sigma.
        profile = _control_profile(frame)
        raw_run = _run_one(
            frame=frame,
            spec=spec,
            model_name=model_name,
            prior_config={"control_sigma": 0.5, "enable_control_scaling": False},
            n_samples=args.n_prior_samples,
            seed=args.seed,
        )
        scaled_run_default_sigma = _run_one(
            frame=frame,
            spec=spec,
            model_name=model_name,
            prior_config={"control_sigma": 0.5, "enable_control_scaling": True},
            n_samples=args.n_prior_samples,
            seed=args.seed,
        )

        # Item 2: control_sigma grid, scaling always on (the analyst-
        # approved direction), never selecting a value.
        grid_rows = []
        for control_sigma in CONTROL_SIGMA_GRID:
            run = _run_one(
                frame=frame,
                spec=spec,
                model_name=model_name,
                prior_config={
                    "control_sigma": control_sigma,
                    "enable_control_scaling": True,
                },
                n_samples=args.n_prior_samples,
                seed=args.seed,
            )
            # component_decomposition only stores summary stats, not raw
            # draws (WP2.5 contract) - rebuild coef/mu draws directly via a
            # second, cheap prior-predictive call scoped to just those two
            # names when the multiplicative-effect distribution is needed.
            proposed = build_model_for_spec(
                frame=frame,
                model_spec=spec,
                model_type="shared",
                dna_lag_weeks=4,
                dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
                prior_config=run["prior_config"],
                direct_dna_outcome_ids=(
                    list(frame["outcome_ids"]) if model_name == "dna_kit" else None
                ),
                causal_graph=None,
                search_objects=(),
            )
            with proposed.model:
                idata = pm.sample_prior_predictive(
                    draws=args.n_prior_samples,
                    random_seed=args.seed,
                    var_names=["control_coef", "mu"],
                )
            control_coef_draws = idata.prior["control_coef"].values.reshape(-1)
            mu_draws = idata.prior["mu"].values.reshape(-1)
            grid_rows.append(_grid_row_from_run(run, control_coef_draws, mu_draws))

        results[model_name] = {
            "control_profile": profile,
            "before_scaling_default_sigma": raw_run,
            "after_scaling_default_sigma": scaled_run_default_sigma,
            "control_sigma_grid": grid_rows,
        }
        _write_json(args.output_dir / f"wp2_6_{model_name}.json", results[model_name])

    print(f"Wrote WP2.6 control-prior calibration evidence to {args.output_dir}")
    for model_name in results:
        print(
            f"  {model_name}: control profile + {len(CONTROL_SIGMA_GRID)}-point grid computed"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
