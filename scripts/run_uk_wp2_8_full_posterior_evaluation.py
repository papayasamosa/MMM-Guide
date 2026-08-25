"""WP2.8 items 5-8 (analyst-directed, 2026-08-25): convergence,
identification, fit-validation, and seasonality evaluation for the real
governed full UK Model A posterior (4 chains x 2000 draws x 1000 tune x
target_accept=0.9 - `scripts/run_uk_production_fit.py`'s own defaults,
REQ-CONTROL-001's approved control-prior already in effect as the
production default).

Loads the already-saved posterior traces from D: (produced by a prior,
separate `scripts/run_uk_production_fit.py` run) and a fresh
prior-predictive sample from the identical model construction for
prior-vs-posterior identification comparison. Does not re-fit, does not
change any prior/transform/pooling/channel default. Reuses
`core.models.compute_model_diagnostics`, `core.diagnostics.
compute_scorecard`/`residual_temporal_diagnostics`, and `core.predict.
extract_posterior_params` - no evidence-computation logic duplicated.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import warnings
from pathlib import Path
from typing import Any

import arviz as az
import numpy as np
import pymc as pm

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.application.model_fit_service import build_model_for_spec  # noqa: E402
from ancestry_mmm.core.diagnostics import (  # noqa: E402
    compute_scorecard,
    error_metrics_by_outcome,
    residual_temporal_diagnostics,
)
from ancestry_mmm.core.models import compute_model_diagnostics  # noqa: E402
from ancestry_mmm.core.predict import extract_posterior_params, predict_mu  # noqa: E402

DEFAULT_TRACE_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-8-full-posterior-20260825"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-8-full-posterior-evaluation-20260825"
)

SPARSE_CHANNELS = {
    "uk_dna_content_marketing",
    "uk_fh_content_marketing",
    "uk_influencer",
    "uk_radio",
    "uk_tv_sponsorship_vod",
    "circulation",
    "uk_fh_midfunnel_social",
}


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


def _flatten_named(values: dict[str, Any], coord: list[str] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, value in values.items():
        if not isinstance(value, list):
            out[name] = float(value)
            continue
        array = np.asarray(value, dtype=float)
        if array.ndim == 0:
            out[name] = float(array)
            continue
        last_axis_labels = coord if coord and len(coord) == array.shape[-1] else None
        for index in np.ndindex(array.shape):
            if last_axis_labels is not None:
                index_label = ",".join(str(i) for i in index[:-1])
                label = last_axis_labels[index[-1]]
                key = (
                    f"{name}[{index_label},{label}]"
                    if index_label
                    else f"{name}[{label}]"
                )
            else:
                key = f"{name}[{','.join(str(i) for i in index)}]"
            out[key] = float(array[index])
    return out


def _param_variable_and_label(key: str) -> tuple[str, str | None]:
    if "[" not in key:
        return key, None
    var_name, _, rest = key.partition("[")
    inside = rest.rstrip("]")
    return var_name, inside.split(",")[-1] if inside else None


def _quantiles(values: np.ndarray) -> dict[str, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {q: float("nan") for q in ("q01", "q05", "q25", "q50", "q75", "q95", "q99")}
    qs = np.quantile(finite, [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99])
    return dict(zip(("q01", "q05", "q25", "q50", "q75", "q95", "q99"), (float(q) for q in qs)))


def _sampler_pathology(idata: az.InferenceData) -> dict[str, Any]:
    stats = idata.sample_stats
    out: dict[str, Any] = {"sample_stats_vars": sorted(stats.data_vars)}
    if "diverging" in stats:
        out["divergences_total"] = int(stats["diverging"].sum())
        out["divergences_by_chain"] = stats["diverging"].sum(dim="draw").values.tolist()
    tree_depth_var = next(
        (v for v in ("tree_depth", "treedepth", "depth") if v in stats), None
    )
    if tree_depth_var is not None:
        depths = stats[tree_depth_var].values
        out["tree_depth_var_used"] = tree_depth_var
        out["max_tree_depth_observed"] = int(depths.max())
        out["max_tree_depth_configured"] = 10
        out["n_draws_at_max_tree_depth_total"] = int(np.sum(depths >= 10))
        out["n_draws_at_max_tree_depth_by_chain"] = np.sum(depths >= 10, axis=1).tolist()
    if "acceptance_rate" in stats:
        out["mean_acceptance_rate_by_chain"] = (
            stats["acceptance_rate"].mean(dim="draw").values.tolist()
        )
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            bfmi = az.bfmi(idata)
        out["bfmi_by_chain"] = np.asarray(bfmi).tolist()
        out["bfmi_min"] = float(np.min(bfmi))
    except Exception as exc:  # noqa: BLE001 - recorded as evidence, not raised
        out["bfmi_error"] = f"{type(exc).__name__}: {exc}"
    return out


def _convergence_summary(
    trace: az.InferenceData, channel_coord: list[str], control_coord: list[str]
) -> dict[str, Any]:
    diagnostics = compute_model_diagnostics(trace)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        ess_tail = az.ess(trace, method="tail")
    ess_tail_by_var = {
        var: (
            float(ess_tail[var].values)
            if ess_tail[var].ndim == 0
            else ess_tail[var].values.tolist()
        )
        for var in ess_tail.data_vars
    }

    def _coord_for(var: str) -> list[str] | None:
        if var in ("hill_K", "hill_S", "decay_rate", "mu_channel", "sigma_pool"):
            return channel_coord
        if var == "control_coef":
            return control_coord
        return None

    rhat_by_param: dict[str, float] = {}
    ess_bulk_by_param: dict[str, float] = {}
    ess_tail_by_param: dict[str, float] = {}
    for var, values in diagnostics["rhat"].items():
        rhat_by_param.update(_flatten_named({var: values}, _coord_for(var)))
    for var, values in diagnostics["ess"].items():
        ess_bulk_by_param.update(_flatten_named({var: values}, _coord_for(var)))
    for var, values in ess_tail_by_var.items():
        ess_tail_by_param.update(_flatten_named({var: values}, _coord_for(var)))

    rhat_values = np.array(list(rhat_by_param.values()))
    ess_bulk_values = np.array(list(ess_bulk_by_param.values()))
    ess_tail_values = np.array(list(ess_tail_by_param.values()))

    worst_rhat = sorted(rhat_by_param.items(), key=lambda kv: kv[1], reverse=True)[:15]
    worst_ess_bulk = sorted(ess_bulk_by_param.items(), key=lambda kv: kv[1])[:15]

    def _family(var_names: set[str], labels: set[str] | None = None) -> dict[str, Any]:
        matched: dict[str, float] = {}
        for k, v in rhat_by_param.items():
            var, label = _param_variable_and_label(k)
            if var in var_names and (labels is None or label in labels):
                matched[k] = v
        if not matched:
            return {"n_params": 0}
        return {
            "n_params": len(matched),
            "rhat_max": max(matched.values()),
            "rhat_mean": float(np.mean(list(matched.values()))),
            "ess_bulk_min": min(
                ess_bulk_by_param[k] for k in matched if k in ess_bulk_by_param
            ),
            "worst_params": sorted(matched.items(), key=lambda kv: kv[1], reverse=True)[:5],
        }

    sparse_present = {c for c in channel_coord if c in SPARSE_CHANNELS}
    non_sparse_present = {c for c in channel_coord if c not in SPARSE_CHANNELS}

    return {
        "rhat_max": diagnostics["rhat_max"],
        "rhat_distribution": _quantiles(rhat_values),
        "ess_bulk_min": diagnostics["ess_min"],
        "ess_bulk_distribution": _quantiles(ess_bulk_values),
        "ess_tail_min": float(np.min(ess_tail_values)) if ess_tail_values.size else None,
        "ess_tail_distribution": _quantiles(ess_tail_values),
        "divergences": diagnostics["divergences"],
        "converged_per_pymc_default_threshold": diagnostics["converged"],
        "worst_rhat_params": worst_rhat,
        "worst_ess_bulk_params": worst_ess_bulk,
        "sampler_pathology": _sampler_pathology(trace),
        "parameter_family_summary": {
            "media_coefficients_beta": _family({"beta"}),
            "decay_adstock": _family({"decay_rate"}),
            "hill_K": _family({"hill_K"}),
            "hill_S": _family({"hill_S"}),
            "controls": _family({"control_coef"}),
            "trend": _family({"trend_coef"}),
            "seasonality_gamma_fourier": _family({"gamma_fourier"}),
            "hierarchy_pooling": _family({"mu_channel", "sigma_pool", "z_offset"}),
            "sparse_channels_hill_adstock": _family(
                {"hill_K", "hill_S", "decay_rate"}, sparse_present
            ),
            "non_sparse_channels_hill_adstock": _family(
                {"hill_K", "hill_S", "decay_rate"}, non_sparse_present
            ),
        },
    }


def _chain_separation(trace: az.InferenceData) -> dict[str, Any]:
    post = trace.posterior
    out: dict[str, Any] = {}
    for var in ("alpha", "intercept"):
        if var not in post:
            continue
        per_chain_mean = post[var].mean(dim="draw")
        # Collapse any extra (e.g. outcome) dims to their own mean so this
        # stays a compact per-chain scalar summary, not a full breakdown -
        # the point is a quick "do the four chains broadly agree" signal,
        # with R-hat (already reported per-parameter above) as the precise
        # cross-chain agreement measure.
        extra_dims = [d for d in per_chain_mean.dims if d != "chain"]
        if extra_dims:
            per_chain_mean = per_chain_mean.mean(dim=extra_dims)
        out[var] = per_chain_mean.values.tolist()
    return out


def _identification_summary(
    posterior: az.InferenceData,
    prior: az.InferenceData,
    channel_coord: list[str],
    control_coord: list[str],
) -> dict[str, Any]:
    def _per_channel(var: str, coord: list[str]) -> dict[str, Any]:
        post_vals = posterior.posterior[var].values.reshape(-1, len(coord))
        prior_vals = prior.prior[var].values.reshape(-1, len(coord))
        rows = {}
        for index, name in enumerate(coord):
            post_col = post_vals[:, index]
            prior_col = prior_vals[:, index]
            post_std = float(np.std(post_col))
            prior_std = float(np.std(prior_col))
            rows[name] = {
                "prior_quantiles": _quantiles(prior_col),
                "posterior_quantiles": _quantiles(post_col),
                "prior_std": prior_std,
                "posterior_std": post_std,
                "posterior_to_prior_std_ratio": (
                    post_std / prior_std if prior_std > 0 else None
                ),
                "weakly_identified": (
                    post_std / prior_std > 0.7 if prior_std > 0 else None
                ),
            }
        return rows

    return {
        "decay_rate": _per_channel("decay_rate", channel_coord),
        "hill_K": _per_channel("hill_K", channel_coord),
        "hill_S": _per_channel("hill_S", channel_coord),
        "control_coef": _per_channel("control_coef", control_coord),
    }


def _seasonality_summary(
    posterior: az.InferenceData,
    prior: az.InferenceData,
    frame: dict[str, Any],
    outcome_ids: list[str],
) -> dict[str, Any]:
    fourier = np.asarray(frame["fourier"], dtype=float)

    def _amplitude_and_coefs(idata: az.InferenceData) -> dict[str, Any]:
        gamma = idata.posterior if "posterior" in idata.groups() else idata.prior
        gamma_fourier = gamma["gamma_fourier"].values
        # dims: (chain, draw, fourier, outcome)
        n_chain, n_draw, n_fourier, n_outcome = gamma_fourier.shape
        flat = gamma_fourier.reshape(n_chain * n_draw, n_fourier, n_outcome)
        amplitude_by_outcome: dict[str, Any] = {}
        coef_by_outcome: dict[str, Any] = {}
        for o_idx, oid in enumerate(outcome_ids):
            eta_season_draws = fourier @ flat[:, :, o_idx].T  # (n_obs, n_draws)
            amplitude = eta_season_draws.max(axis=0) - eta_season_draws.min(axis=0)
            amplitude_by_outcome[oid] = _quantiles(amplitude)
            coef_by_outcome[oid] = {
                f"fourier_{i}": _quantiles(flat[:, i, o_idx])
                for i in range(n_fourier)
            }
        return {"amplitude_by_outcome": amplitude_by_outcome, "coefficients_by_outcome": coef_by_outcome}

    return {
        "prior": _amplitude_and_coefs(prior),
        "posterior": _amplitude_and_coefs(posterior),
    }


def _competition_check(
    posterior: az.InferenceData, outcome_ids: list[str]
) -> dict[str, Any]:
    """Correlate each outcome's posterior-mean eta_season time series
    against eta_trend/eta_channels/eta_controls, to see whether
    seasonality tracks (competes with) any of them - a simple, direct
    diagnostic rather than a formal collinearity test."""
    post = posterior.posterior
    out: dict[str, Any] = {}
    if "eta_season" not in post:
        return out
    season_mean = post["eta_season"].mean(dim=("chain", "draw")).values  # (obs, outcome)
    for other in ("eta_trend", "eta_channels", "eta_controls"):
        if other not in post:
            continue
        other_mean = post[other].mean(dim=("chain", "draw")).values
        correlations = []
        for o_idx, oid in enumerate(outcome_ids):
            a, b = season_mean[:, o_idx], other_mean[:, o_idx]
            corr = (
                float(np.corrcoef(a, b)[0, 1])
                if np.std(a) > 0 and np.std(b) > 0
                else None
            )
            correlations.append({"outcome_id": oid, "correlation": corr})
        out[other] = correlations
    return out


def _actual_vs_predicted(
    frame: dict[str, Any], meta: Any, params: Any, outcome_ids: list[str]
) -> dict[str, Any]:
    mu = predict_mu(frame, meta, params)
    Y = np.asarray(frame["Y"], dtype=float)
    dates = frame.get("dates")
    date_strs = (
        [str(d)[:10] for d in dates] if dates is not None else list(range(Y.shape[0]))
    )
    out = {}
    for o_idx, oid in enumerate(outcome_ids):
        out[oid] = {
            "dates": date_strs,
            "actual": Y[:, o_idx].tolist(),
            "predicted_mean": mu[:, o_idx].tolist(),
        }
    return out


def _evaluate_model(
    model_name: str,
    frame: dict[str, Any],
    spec: Any,
    prior_config: dict[str, Any],
    trace_dir: Path,
    output_dir: Path,
    seed: int,
) -> dict[str, Any]:
    trace_path = trace_dir / model_name / "posterior.nc"
    posterior = az.from_netcdf(trace_path)

    channel_coord = [str(c) for c in frame["channels"]]
    control_coord = [str(c) for c in (frame.get("control_names") or [])]
    outcome_ids = [str(o) for o in frame["outcome_ids"]]

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
    with proposed.model:
        prior_idata = pm.sample_prior_predictive(
            draws=8000,
            random_seed=seed,
            var_names=["decay_rate", "hill_K", "hill_S", "gamma_fourier", "control_coef"],
        )

    convergence = _convergence_summary(posterior, channel_coord, control_coord)
    chain_separation = _chain_separation(posterior)
    identification = _identification_summary(
        posterior, prior_idata, channel_coord, control_coord
    )
    seasonality = _seasonality_summary(posterior, prior_idata, frame, outcome_ids)
    competition = _competition_check(posterior, outcome_ids)

    params = extract_posterior_params(posterior, proposed.meta)
    scorecard = compute_scorecard(posterior, frame, proposed.meta)
    residuals = residual_temporal_diagnostics(frame, proposed.meta, params)
    error_metrics = error_metrics_by_outcome(frame, proposed.meta, params)
    actual_vs_predicted = _actual_vs_predicted(frame, proposed.meta, params, outcome_ids)

    result = {
        "model_name": model_name,
        "trace_path": str(trace_path),
        "sampler_config": {
            "draws": 2000,
            "tune": 1000,
            "chains": 4,
            "target_accept": 0.9,
        },
        "convergence": convergence,
        "chain_separation": chain_separation,
        "identification": identification,
        "seasonality": seasonality,
        "seasonality_competition_correlation": competition,
        "in_sample_fit": scorecard["in_sample_fit"],
        "error_metrics": error_metrics.to_dict(orient="records"),
        "ppc_coverage": scorecard["ppc_coverage"],
        "plausibility_flags": scorecard["plausibility_flags"],
        "residual_temporal_diagnostics": residuals.to_dict(orient="records"),
        "actual_vs_predicted": actual_vs_predicted,
    }
    _write_json(output_dir / f"wp2_8_full_posterior_evaluation_{model_name}.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only-model", choices=["family_history", "dna_kit"])
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    prior_config = dict(runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG)

    captured: dict[str, tuple[dict[str, Any], Any]] = {}

    def _capture(model_name: str, frame: dict[str, Any], spec: Any) -> None:
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
        prior_config=prior_config,
        frame_callback=_capture,
    )

    for model_name, (frame, spec) in captured.items():
        result = _evaluate_model(
            model_name,
            frame,
            spec,
            prior_config,
            args.trace_dir,
            args.output_dir,
            args.seed,
        )
        conv = result["convergence"]
        print(
            f"{model_name}: rhat_max={conv['rhat_max']:.4f} "
            f"ess_bulk_min={conv['ess_bulk_min']:.1f} "
            f"divergences={conv['divergences']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
