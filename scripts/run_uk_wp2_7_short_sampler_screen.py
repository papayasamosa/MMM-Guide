"""WP2.7 item 6 (analyst-directed, 2026-08-25): short Bayesian sampler
screening stage for the current UK Model A candidate, under
REQ-CONTROL-001's approved control-prior configuration
(`APPROVED_UK_MODEL_A_PRIOR_CONFIG`).

Sampler configuration is deliberately the repository's own existing
short-screen precedent - not an invented threshold - matching
`scripts/run_uk_transform_identifiability_experiment.py`'s CLI defaults
(`--draws 100 --tune 150 --chains 2 --target-accept 0.95`), the same
configuration `docs/model_a_convergence_remediation_20260822.md` already
describes running for this exact purpose ("Family History 2x100",
"DNA 2x100"). This is a real NUTS run (not prior-predictive-only), but a
short screen only - `docs/approved_requirements/REQ-PREFIT-001.md`:
"a short screen does not establish production convergence." No media
prior, adstock, Hill saturation, pooling, channel selection, causal
role, or fold policy is changed - the only thing different from the
existing production default path is REQ-CONTROL-001's control-prior
change, which is now that default. This script does not start the full
WP3 production fit; it stops after reporting this screen's evidence.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.application.model_fit_service import build_model_for_spec  # noqa: E402
from ancestry_mmm.core.diagnostics import (  # noqa: E402
    compute_scorecard,
    residual_temporal_diagnostics,
)
from ancestry_mmm.core.models import compute_model_diagnostics, fit_model  # noqa: E402
from ancestry_mmm.core.predict import extract_posterior_params  # noqa: E402

DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-7-short-sampler-screen-20260825"
)

# Matches scripts/run_uk_transform_identifiability_experiment.py's own CLI
# defaults exactly - the repository's existing short-screen precedent,
# already used for this exact purpose per
# docs/model_a_convergence_remediation_20260822.md. Not invented here.
SHORT_SCREEN_DRAWS = 100
SHORT_SCREEN_TUNE = 150
SHORT_SCREEN_CHAINS = 2
SHORT_SCREEN_TARGET_ACCEPT = 0.95

# WP2.5's sparse-channel review (docs/wp2_5_diagnostic_investigation_
# findings_20260824.md, section 3) - reused here, not recomputed, to
# classify per-channel convergence pathology by known sparsity.
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
    """`compute_model_diagnostics`'s per-variable rhat/ess dict has either a
    bare float (scalar variable), a flat list aligned to that variable's own
    coordinate (e.g. `control`, `channel`), or - for a variable with more
    than one dimension (e.g. `mu_channel`, `gamma_fourier`) - a nested list.
    This flattens any shape via numpy and labels each entry positionally,
    using `coord` for the last axis when its length matches (the axis this
    module's variables consistently use for the channel/control
    coordinate), so per-parameter pathology can still be grouped by name."""
    out: dict[str, float] = {}
    for name, value in values.items():
        if not isinstance(value, list):
            out[name] = float(value)
            continue
        array = np.asarray(value, dtype=float)
        if array.ndim == 0:
            out[name] = float(array)
            continue
        last_axis_labels = (
            coord if coord and len(coord) == array.shape[-1] else None
        )
        for index in np.ndindex(array.shape):
            if last_axis_labels is not None:
                index_label = ",".join(str(i) for i in index[:-1])
                label = last_axis_labels[index[-1]]
                key = f"{name}[{index_label},{label}]" if index_label else f"{name}[{label}]"
            else:
                key = f"{name}[{','.join(str(i) for i in index)}]"
            out[key] = float(array[index])
    return out


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
        max_observed = int(depths.max())
        out["tree_depth_var_used"] = tree_depth_var
        out["max_tree_depth_observed"] = max_observed
        # PyMC's NUTS default max_treedepth is 10 - fit_model does not
        # override it, so 10 is what this run actually used.
        out["max_tree_depth_configured"] = 10
        out["n_draws_at_max_tree_depth"] = int(
            np.sum(depths >= out["max_tree_depth_configured"])
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


def _run_one(
    *,
    model_name: str,
    frame: dict[str, Any],
    spec: Any,
    prior_config: dict[str, Any],
    output_dir: Path,
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

    trace = fit_model(
        proposed.model,
        draws=SHORT_SCREEN_DRAWS,
        tune=SHORT_SCREEN_TUNE,
        chains=SHORT_SCREEN_CHAINS,
        target_accept=SHORT_SCREEN_TARGET_ACCEPT,
        random_seed=seed,
        cores=1,
    )
    trace_path = output_dir / f"{model_name}_short_screen_posterior.nc"
    trace.to_netcdf(trace_path)

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

    channel_coord = list(frame.get("channels") or [])
    control_coord = list(frame.get("control_names") or [])
    rhat_by_param: dict[str, float] = {}
    ess_bulk_by_param: dict[str, float] = {}
    ess_tail_by_param: dict[str, float] = {}
    for var, values in diagnostics["rhat"].items():
        coord = (
            channel_coord
            if var in ("hill_K", "hill_S", "decay_rate", "mu_channel")
            else control_coord
            if var == "control_coef"
            else None
        )
        rhat_by_param.update(_flatten_named({var: values}, coord))
    for var, values in diagnostics["ess"].items():
        coord = (
            channel_coord
            if var in ("hill_K", "hill_S", "decay_rate", "mu_channel")
            else control_coord
            if var == "control_coef"
            else None
        )
        ess_bulk_by_param.update(_flatten_named({var: values}, coord))
    for var, values in ess_tail_by_var.items():
        coord = (
            channel_coord
            if var in ("hill_K", "hill_S", "decay_rate", "mu_channel")
            else control_coord
            if var == "control_coef"
            else None
        )
        ess_tail_by_param.update(_flatten_named({var: values}, coord))

    def _param_variable_and_label(key: str) -> tuple[str, str | None]:
        """`_flatten_named` always writes `var[...]` with the channel/
        control name (when known) as the last comma-separated component
        inside the brackets - this recovers both parts regardless of a
        variable's actual dimensionality."""
        if "[" not in key:
            return key, None
        var_name, _, rest = key.partition("[")
        inside = rest.rstrip("]")
        return var_name, inside.split(",")[-1] if inside else None

    def _group(var_names: set[str], labels: set[str] | None = None) -> dict[str, Any]:
        matched_rhat: dict[str, float] = {}
        for k, v in rhat_by_param.items():
            var, label = _param_variable_and_label(k)
            if var in var_names and (labels is None or label in labels):
                matched_rhat[k] = v
        if not matched_rhat:
            return {"n_params": 0}
        return {
            "n_params": len(matched_rhat),
            "rhat_max": max(matched_rhat.values()),
            "rhat_mean": float(np.mean(list(matched_rhat.values()))),
            "worst_params": sorted(
                matched_rhat.items(), key=lambda kv: kv[1], reverse=True
            )[:5],
        }

    hill_adstock_var_names = {"hill_K", "hill_S", "decay_rate", "mu_channel"}
    sparse_channels_present = {c for c in channel_coord if c in SPARSE_CHANNELS}
    non_sparse_channels_present = {c for c in channel_coord if c not in SPARSE_CHANNELS}

    pathology_by_group = {
        "category_demand_control": _group({"control_coef"}),
        "sparse_channels_hill_adstock": _group(
            hill_adstock_var_names, sparse_channels_present
        ),
        "non_sparse_channels_hill_adstock": _group(
            hill_adstock_var_names, non_sparse_channels_present
        ),
        "all_hill_adstock": _group(hill_adstock_var_names),
    }

    params = extract_posterior_params(trace, proposed.meta)
    scorecard = compute_scorecard(trace, frame, proposed.meta)
    residuals = residual_temporal_diagnostics(frame, proposed.meta, params)

    return {
        "model_name": model_name,
        "sampler_config": {
            "draws": SHORT_SCREEN_DRAWS,
            "tune": SHORT_SCREEN_TUNE,
            "chains": SHORT_SCREEN_CHAINS,
            "target_accept": SHORT_SCREEN_TARGET_ACCEPT,
            "seed": seed,
        },
        "prior_config_used": dict(prior_config),
        "trace_path": str(trace_path),
        "convergence": {
            "rhat_max": diagnostics["rhat_max"],
            "ess_bulk_min": diagnostics["ess_min"],
            "ess_tail_min": min(
                np.min(v) if isinstance(v, list) else v
                for v in ess_tail_by_var.values()
            ),
            "divergences": diagnostics["divergences"],
            "converged": diagnostics["converged"],
        },
        "sampler_pathology": _sampler_pathology(trace),
        "pathology_by_parameter_group": pathology_by_group,
        "in_sample_fit": scorecard["in_sample_fit"],
        "ppc_coverage": scorecard["ppc_coverage"],
        "plausibility_flags": scorecard["plausibility_flags"],
        "residual_temporal_diagnostics": residuals.to_dict(orient="records"),
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

    results: dict[str, Any] = {}
    for model_name, (frame, spec) in captured.items():
        result = _run_one(
            model_name=model_name,
            frame=frame,
            spec=spec,
            prior_config=prior_config,
            output_dir=args.output_dir,
            seed=args.seed + (0 if model_name == "family_history" else 1),
        )
        results[model_name] = result
        _write_json(
            args.output_dir / f"wp2_7_short_sampler_screen_{model_name}.json", result
        )
        print(
            f"{model_name}: rhat_max={result['convergence']['rhat_max']:.3f} "
            f"ess_bulk_min={result['convergence']['ess_bulk_min']:.1f} "
            f"divergences={result['convergence']['divergences']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
