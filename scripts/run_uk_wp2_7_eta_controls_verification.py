"""WP2.7 item 4 (analyst-directed, 2026-08-25): confirm end-to-end that
`scripts/run_uk_production_fit.py`'s new default
(`APPROVED_UK_MODEL_A_PRIOR_CONFIG`, REQ-CONTROL-001) actually reaches
`eta_controls`'s prior-predictive behaviour as approved - i.e. this
verifies the real production code path (not a re-run of WP2.6's own
diagnostic grid, which already computed the same `control_sigma=0.20`
point separately). Prior-predictive sampling only; no NUTS/MCMC, no
observed data read by the sampler; no channel/prior/pooling change.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.application.model_fit_service import build_model_for_spec  # noqa: E402
from ancestry_mmm.core.diagnostics import prior_predictive_summary  # noqa: E402

DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-7-eta-controls-verification-20260825"
)
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


def _pathology_summary(mu_draws: np.ndarray) -> dict[str, Any]:
    finite = mu_draws[np.isfinite(mu_draws)]
    return {
        "n_draws": int(mu_draws.size),
        "n_non_finite": int(mu_draws.size - finite.size),
        "n_clipped_at_floor_1e_minus_6": int(np.sum(finite <= 1e-6 + 1e-12)),
        "n_clipped_at_ceiling_1e9": int(np.sum(finite >= 1e9 - 1.0)),
    }


def main(argv: list[str] | None = None) -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--n-prior-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Deliberately the script's real default (not a --prior-config
    # override) - this is what `main()` now uses for every production
    # invocation with no flags, per REQ-CONTROL-001.
    prior_config = runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG
    assert prior_config == {
        "control_sigma": 0.20,
        "enable_control_scaling": True,
    }, "APPROVED_UK_MODEL_A_PRIOR_CONFIG drifted from REQ-CONTROL-001's approved value"

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
        only_model=None,
        governed_start=args.governed_start,
        governed_end=args.governed_end,
        prior_config=prior_config,
        frame_callback=_capture,
    )

    results: dict[str, Any] = {}
    for model_name, (frame, spec) in captured.items():
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
            n_samples=args.n_prior_samples,
            random_seed=args.seed,
            component_var_names=COMPONENT_VAR_NAMES,
        )
        plausibility = result["plausibility"]
        components = (plausibility.get("component_decomposition") or {}).get(
            "components", {}
        )

        import pymc as pm

        with proposed.model:
            idata = pm.sample_prior_predictive(
                draws=args.n_prior_samples,
                random_seed=args.seed,
                var_names=["control_coef", "mu"],
            )
        control_coef_draws = idata.prior["control_coef"].values.reshape(-1)
        mu_draws = idata.prior["mu"].values.reshape(-1)

        results[model_name] = {
            "prior_config_used": dict(prior_config),
            "control_scaling_contract": proposed.meta.control_scaling,
            "eta_controls": components.get("eta_controls"),
            "control_coef_multiplicative_effect_per_sd": {
                "q01": float(np.quantile(np.exp(control_coef_draws), 0.01)),
                "q05": float(np.quantile(np.exp(control_coef_draws), 0.05)),
                "q50": float(np.quantile(np.exp(control_coef_draws), 0.50)),
                "q95": float(np.quantile(np.exp(control_coef_draws), 0.95)),
                "q99": float(np.quantile(np.exp(control_coef_draws), 0.99)),
            },
            "mu_pathology": _pathology_summary(mu_draws),
            "outcome_rows": plausibility["rows"],
        }
        _write_json(
            args.output_dir / f"wp2_7_eta_controls_verification_{model_name}.json",
            results[model_name],
        )
        print(
            f"{model_name}: eta_controls median={components.get('eta_controls', {}).get('median')}, "
            f"pathology={results[model_name]['mu_pathology']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
