"""Build-and-prior-sample validation for every WP2 candidate model.
Catches graph/shape/overflow errors without running MCMC."""

import pymc as pm

from scripts.wp2_named_event_response.candidates import (
    CANDIDATES,
    build_multi_market_model,
    build_single_market_model,
)
from scripts.wp2_named_event_response.dgp import (
    build_multi_market_scenario,
    build_scenarios,
)


def _check(model: pm.Model, label: str) -> None:
    with model:
        pm.sample_prior_predictive(draws=2, random_seed=1)
    print(f"ok {label}")


def main() -> None:
    scenario = build_scenarios()[0]
    for candidate in CANDIDATES:
        _check(build_single_market_model(scenario, candidate), f"single {candidate}")

    multi_shared = build_multi_market_scenario("shared")
    for candidate in CANDIDATES:
        _check(
            build_multi_market_model(multi_shared, candidate),
            f"multi shared {candidate}",
        )

    multi_model_c = build_multi_market_scenario("market_specific")
    for candidate in ("S2_parametric", "S5_pooled_basis"):
        _check(
            build_multi_market_model(multi_model_c, candidate),
            f"multi model_c {candidate}",
        )
    print("all builds ok")


if __name__ == "__main__":
    main()
