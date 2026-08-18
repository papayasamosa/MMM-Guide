"""Work Package 1 part 1 (`Media-Mix-Lab: Coding LLM Next Steps After PR
#284`): real `pm.sample` NUTS fold-refit evidence for
`application.fold_refit_service` beyond what test_fold_refit_service.py's
single tiny shared-model fit covers.

Separated from test_fold_refit_service.py (one fast, blocking-CI-safe fit)
so this file can be excluded from the ordinary Python 3.11/3.12 test jobs
and run instead by the dedicated `fold-refit-recovery` schedule/manual-only
CI job - the same pattern test_search_candidate_a_recovery_posterior.py's
own module docstring describes and the `candidate-a-recovery` job already
uses for the Candidate A engine's MCMC cost. Covers:

- Market-specific (Model C) real fit and market-qualified snapshot naming.
- The single-market fallback path (Model C requested, one market present).
- Genuine multi-fold structural-stability evidence: two real fits feeding
  `core.structural_stability.assess_structural_stability`, not a real fit
  plus a synthetic stand-in fold.

Evidence, not an official-use approval: these tests confirm the real-fit
wiring produces sane, finite, correctly-shaped evidence at a moderate
budget - they are not a statistical parameter-recovery claim (unlike
test_search_candidate_a_recovery_posterior.py, there is no independent
"known ground truth" generator here to recover against).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ancestry_mmm.application.fold_refit_service import (
    fit_fold_with_real_model,
    run_leakage_safe_fold_refit,
)
from ancestry_mmm.application.model_fit_service import (
    MODEL_TYPE_MARKET_SPECIFIC,
    MODEL_TYPE_SHARED,
)
from ancestry_mmm.core.coverage import VariableCoverageMatrix
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.structural_stability import assess_structural_stability

FIT_KWARGS = dict(
    draws=200, tune=200, chains=2, cores=1, target_accept=0.9, random_seed=7
)


def _raw_dataframe(n_weeks: int, markets: tuple[str, ...]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n_weeks, freq="W")
    frames = []
    for i, market in enumerate(markets):
        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "market": market,
                    "TV_Brand": np.linspace(100.0 + i * 10, 900.0 + i * 10, n_weeks),
                    "GSA_New": np.linspace(20.0 + i * 5, 120.0 + i * 5, n_weeks),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _spec(markets: tuple[str, ...]) -> ModelSpec:
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=list(markets),
        segment_outcomes={"New": "GSA_New"},
        channels=["TV_Brand"],
    )


def _empty_coverage_matrix() -> VariableCoverageMatrix:
    return VariableCoverageMatrix(
        matrix_id="empty-matrix",
        matrix_version=1,
        generated_at="2026-08-18",
        records=(),
    )


class TestMarketSpecificRealFit:
    def test_snapshot_uses_market_qualified_naming(self):
        markets = ("UK", "US")
        raw_df = _raw_dataframe(n_weeks=40, markets=markets)
        spec = _spec(markets)
        dates = pd.to_datetime(raw_df[spec.date_col])
        cutoff = dates.quantile(0.7)
        train_df = raw_df[dates <= cutoff]
        test_df = raw_df[dates > cutoff]

        outcome = fit_fold_with_real_model(
            train_df,
            test_df,
            spec,
            fold_id="fold_market_specific",
            model_type=MODEL_TYPE_MARKET_SPECIFIC,
            posterior_draw_subsample=20,
            **FIT_KWARGS,
        )
        snapshot = outcome.snapshot

        for expected_key in (
            "adstock_decay__TV_Brand",  # shared across markets in Model C
            "hill_K__UK__TV_Brand",
            "hill_K__US__TV_Brand",
            "beta__UK__TV_Brand__fh_new",
            "beta__US__TV_Brand__fh_new",
        ):
            assert expected_key in snapshot.point_values, expected_key
            assert np.isfinite(snapshot.point_values[expected_key])
        assert np.isfinite(outcome.r2_by_outcome["fh_new"])


class TestSingleMarketFallback:
    def test_falls_back_to_shared_when_fewer_than_two_markets(self):
        """Mirrors pages/06_Diagnostics.py's existing fit_fold closure:
        model_type='market_specific' with <2 markets in the fold's own
        training slice falls back to the shared builder rather than
        raising - a fold-local market dropout does not itself abort the
        backtest."""
        markets = ("UK",)
        raw_df = _raw_dataframe(n_weeks=40, markets=markets)
        spec = _spec(markets)
        dates = pd.to_datetime(raw_df[spec.date_col])
        cutoff = dates.quantile(0.7)
        train_df = raw_df[dates <= cutoff]
        test_df = raw_df[dates > cutoff]

        outcome = fit_fold_with_real_model(
            train_df,
            test_df,
            spec,
            fold_id="fold_single_market",
            model_type=MODEL_TYPE_MARKET_SPECIFIC,
            posterior_draw_subsample=20,
            **FIT_KWARGS,
        )

        assert not any(
            k.startswith("hill_K__UK__") for k in outcome.snapshot.point_values
        )
        assert "hill_K__TV_Brand" in outcome.snapshot.point_values


class TestGenuineMultiFoldStructuralStability:
    def test_two_real_fits_feed_structural_stability(self):
        markets = ("UK", "US")
        raw_df = _raw_dataframe(n_weeks=60, markets=markets)
        spec = _spec(markets)

        result = run_leakage_safe_fold_refit(
            raw_df,
            spec,
            _empty_coverage_matrix(),
            model_type=MODEL_TYPE_SHARED,
            n_folds=2,
            min_train_frac=0.6,
            posterior_draw_subsample=20,
            **FIT_KWARGS,
        )

        assert len(result.snapshots) == 2
        artefact = assess_structural_stability(result.snapshots)

        assert artefact.fold_ids == tuple(s.fold_id for s in result.snapshots)
        by_name = {p.parameter_name: p for p in artefact.per_parameter}
        assert "hill_K__TV_Brand" in by_name
        comparison = by_name["hill_K__TV_Brand"]
        assert len(comparison.fold_point_values) == 2
        assert np.isfinite(comparison.point_range)
