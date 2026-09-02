"""
Diagnostics service — provides model diagnostics and scorecard evaluation
without Streamlit dependencies.

PR 72B: Canonical diagnostics evidence. Each diagnostic is computed once
and stored in a fingerprinted DiagnosticsArtefact (schema v3, see
``CURRENT_DIAGNOSTICS_SCHEMA_VERSION`` below - schema v2 at PR 72B's
original introduction) with full serialisable payloads and explicit
section statuses. No missing evidence is encoded as zero. ValidationService
reads metrics from this artefact rather than recomputing them.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
import warnings
from datetime import datetime, timezone
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
)

import numpy as np
import pandas as pd
import arviz as az
import pymc as pm

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.diagnostics import (
    error_metrics_by_outcome,
    in_sample_fit,
    posterior_predictive_coverage,
    posterior_predictive_metric_distributions,
    curve_plausibility_checks,
    expanding_window_backtest,
    predictive_density_summary,
    prior_predictive_summary,
    residual_series,
    residual_temporal_diagnostics,
    shared_residual_evidence,
)
from ancestry_mmm.core.market_specific_diagnostics import (
    error_metrics_by_outcome_market_specific,
    in_sample_fit_market_specific,
    curve_plausibility_checks_market_specific,
    posterior_predictive_metric_distributions_market_specific,
    residual_series_market_specific,
    residual_temporal_diagnostics_market_specific,
)
from ancestry_mmm.core.identification_diagnostics import (
    channel_spend_correlation_matrix,
    design_matrix_condition_number,
    identification_report,
    posterior_coefficient_stability,
)
from ancestry_mmm.core.market_data_capability import check_market_channel_capability
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.core.market_specific_predict import (
    extract_market_specific_posterior_params,
)
from ancestry_mmm.core.search_capacity import (
    SEARCH_CANDIDATE_A_ENGINE,
    candidate_a_use_gate,
    extract_candidate_a_search_posterior_summary,
    identify_candidate_a_search,
    validate_candidate_a_spec,
)
from ancestry_mmm.core.estimand_identification import (
    EFFECT_TYPE_TOTAL,
    assess_backdoor_identification,
)
from ancestry_mmm.core.latent_state_identification import (
    assess_latent_state_identification,
)
from ancestry_mmm.core.validation_folds import (
    RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY,
    RECONSTRUCTION_TIERS,
    FoldReconstructionAssessment,
    ValidationFold,
)
from ancestry_mmm.core.structural_stability import (
    FoldParameterSnapshot,
    assess_structural_stability,
)

# Diagnostics artefact schema (moved to core.diagnostics_artefact, WP3
# 2026-08-27 - docs/wp3_diagnostics_coupling_refactor_plan.md Phase 1):
# DiagnosticSection, DiagnosticsArtefact, DiagnosticsInput, DiagnosticsResult,
# CURRENT_DIAGNOSTICS_SCHEMA_VERSION, and CURRENT_DIAGNOSTICS_VERSION now
# live in core.diagnostics_artefact (pure-data, no PyMC/Streamlit
# dependency) - re-exported here unchanged so every existing
# `from ancestry_mmm.application.diagnostics_service import
# DiagnosticsArtefact`-style import continues to resolve to the exact same
# class object. See core.diagnostics_artefact's own module docstring for
# the full schema-version history this comment previously carried.
from ancestry_mmm.core.diagnostics_artefact import (  # noqa: F401
    CURRENT_DIAGNOSTICS_SCHEMA_VERSION,
    CURRENT_DIAGNOSTICS_VERSION,
    DiagnosticSection,
    DiagnosticSectionStatus,
    DiagnosticsArtefact,
    DiagnosticsInput,
    DiagnosticsResult,
)

# Work Package 2 (`Media-Mix-Lab: Coding LLM Next Steps After PR #286`,
# canonical Diagnostics evidence integration): the stable identifier this
# module uses to diagnose Candidate A's latent branded-search-demand state
# via `core.latent_state_identification`. This is a diagnostics-layer
# bookkeeping label only - it asserts no specific identifying anchor for
# the state (REQ-LATENT-001's own substantive anchor choice, Part 6
# `MD-021`, remains an explicitly unresolved decision this record does not
# make).
CANDIDATE_A_LATENT_DEMAND_STATE_ID = "candidate_a_latent_branded_search_demand"


# ---------------------------------------------------------------------------
# DiagnosticsService
# ---------------------------------------------------------------------------


class DiagnosticsService:
    """Application service for model diagnostics.

    PR 72B: Computes each diagnostic once. The artefact stores complete
    payloads with explicit section statuses. No missing evidence is
    encoded as zero.
    """

    def evaluate(self, diag_input: DiagnosticsInput) -> DiagnosticsResult:
        """Run diagnostics and return a structured result with a current-schema artefact."""
        errors: List[str] = []
        warnings: List[str] = []

        if diag_input.trace is None:
            errors.append("No posterior trace provided.")
            return DiagnosticsResult(
                scorecard={},
                max_rhat=float("nan"),
                min_ess=float("nan"),
                has_divergences=False,
                mean_ppc_coverage_pct=float("nan"),
                errors=errors,
            )

        # --- 1. Convergence (single authoritative calculation) ---
        convergence_sec: DiagnosticSection
        try:
            max_rhat, min_ess, divergence_count = self._check_convergence(
                diag_input.trace
            )
            has_div = divergence_count > 0
            # Same convergence formula as the (now removed) duplicate check
            # previously embedded in compute_scorecard()/DiagnosticsResult.
            # convergence_ok - not a new/invented threshold.
            converged = max_rhat < 1.05 and min_ess > 200 and not has_div
            convergence_payload = {
                "max_rhat": max_rhat,
                "min_ess": min_ess,
                "has_divergences": has_div,
                "divergences": divergence_count,
                "converged": converged,
            }
            convergence_sec = DiagnosticSection(
                status="computed",
                payload=convergence_payload,
            )
        except Exception as exc:
            errors.append(f"Convergence check failed: {exc}")
            max_rhat, min_ess, has_div = float("nan"), float("nan"), True
            divergence_count, converged = 0, False
            convergence_payload = {
                "max_rhat": max_rhat,
                "min_ess": min_ess,
                "has_divergences": has_div,
                "divergences": divergence_count,
                "converged": converged,
            }
            convergence_sec = DiagnosticSection(
                status="failed", payload=None, error=str(exc)
            )

        # --- 2. In-sample fit (single authoritative calculation - does not
        # recompute convergence/PPC/plausibility the way compute_scorecard()
        # does internally) ---
        fit_sec: DiagnosticSection
        fit_records: List[Dict[str, Any]] = []
        try:
            if diag_input.model_type == "market_specific":
                market_fit_params = extract_market_specific_posterior_params(
                    diag_input.trace, diag_input.meta
                )
                fit_df = in_sample_fit_market_specific(
                    diag_input.frame,
                    diag_input.meta,
                    market_fit_params,
                    named_event_fit_inputs=diag_input.named_event_fit_inputs,
                )
            else:
                shared_fit_params = extract_posterior_params(
                    diag_input.trace, diag_input.meta
                )
                fit_df = in_sample_fit(
                    diag_input.frame,
                    diag_input.meta,
                    shared_fit_params,
                    named_event_fit_inputs=diag_input.named_event_fit_inputs,
                )
            fit_records = fit_df.to_dict(orient="records")
            fit_sec = DiagnosticSection(
                status="computed",
                payload=fit_records,
            )
        except Exception as exc:
            errors.append(f"In-sample fit computation failed: {exc}")
            fit_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))

        # --- 2b/2c. Error metrics (MAE/RMSE/sMAPE/WAPE/bias) and residual
        # temporal diagnostics (lag-1 autocorrelation/Durbin-Watson) - REQ-
        # VAL-001 UK-pilot evidence expansion. Independent single-authoritative
        # calculations, alongside (never inside) in-sample fit above, so a
        # failure in one never hides the other. Deliberately reports evidence
        # only - no blocking threshold is introduced here. ---
        error_metrics_sec: DiagnosticSection
        residual_diagnostics_sec: DiagnosticSection
        try:
            if diag_input.model_type == "market_specific":
                market_em_params = extract_market_specific_posterior_params(
                    diag_input.trace, diag_input.meta
                )
                error_df = error_metrics_by_outcome_market_specific(
                    diag_input.frame,
                    diag_input.meta,
                    market_em_params,
                    named_event_fit_inputs=diag_input.named_event_fit_inputs,
                )
                residual_df = residual_temporal_diagnostics_market_specific(
                    diag_input.frame,
                    diag_input.meta,
                    market_em_params,
                    named_event_fit_inputs=diag_input.named_event_fit_inputs,
                )
            else:
                shared_em_params = extract_posterior_params(
                    diag_input.trace, diag_input.meta
                )
                error_df = error_metrics_by_outcome(
                    diag_input.frame,
                    diag_input.meta,
                    shared_em_params,
                    named_event_fit_inputs=diag_input.named_event_fit_inputs,
                )
                residual_df = residual_temporal_diagnostics(
                    diag_input.frame,
                    diag_input.meta,
                    shared_em_params,
                    named_event_fit_inputs=diag_input.named_event_fit_inputs,
                )
            error_metrics_sec = DiagnosticSection(
                status="computed", payload=error_df.to_dict(orient="records")
            )
            residual_diagnostics_sec = DiagnosticSection(
                status="computed", payload=residual_df.to_dict(orient="records")
            )
        except Exception as exc:
            errors.append(f"Error metrics / residual diagnostics failed: {exc}")
            error_metrics_sec = DiagnosticSection(
                status="failed", payload=None, error=str(exc)
            )
            residual_diagnostics_sec = DiagnosticSection(
                status="failed", payload=None, error=str(exc)
            )

        # --- 2c-bis. Canonical per-market x date x outcome_id residual
        # evidence (WP2.11 item 6, the Residual Explorer's data source) +
        # cross-outcome shared-residual comparison. A separate try/except
        # from error_metrics/residual_diagnostics above - same "independent
        # single-authoritative calculation" pattern every section here
        # follows, so a failure here never hides the aggregate lag-1/
        # Durbin-Watson evidence above (or vice versa). Reuses the exact
        # same per-draw params already extracted above (no second
        # extraction). ---
        residual_series_sec: DiagnosticSection
        try:
            if diag_input.model_type == "market_specific":
                residual_series_df = residual_series_market_specific(
                    diag_input.frame,
                    diag_input.meta,
                    market_em_params,
                    trace=diag_input.trace,
                    credible_mass=diag_input.credible_mass,
                    named_event_fit_inputs=diag_input.named_event_fit_inputs,
                )
            else:
                residual_series_df = residual_series(
                    diag_input.frame,
                    diag_input.meta,
                    shared_em_params,
                    trace=diag_input.trace,
                    credible_mass=diag_input.credible_mass,
                    named_event_fit_inputs=diag_input.named_event_fit_inputs,
                )
            residual_series_sec = DiagnosticSection(
                status="computed",
                payload={
                    "rows": residual_series_df.to_dict(orient="records"),
                    "shared_residual_evidence": shared_residual_evidence(
                        residual_series_df
                    ),
                },
            )
        except Exception as exc:
            errors.append(f"Residual series computation failed: {exc}")
            residual_series_sec = DiagnosticSection(
                status="failed", payload=None, error=str(exc)
            )

        # --- 2d. Posterior predictive metric distributions (REQ-PPD-001,
        # Work Package 2) - reuses the trace/frame/meta/params already
        # available for error_metrics above (no extra fit; `trace.
        # posterior["mu"]` is already materialised for the fitted model).
        # A separate try/except from error_metrics above so a failure in
        # one never hides the other - the same "independent single-
        # authoritative calculation" pattern every other section here
        # follows. ---
        ppd_sec: DiagnosticSection
        try:
            if diag_input.model_type == "market_specific":
                market_ppd_params = extract_market_specific_posterior_params(
                    diag_input.trace, diag_input.meta
                )
                ppd_df = posterior_predictive_metric_distributions_market_specific(
                    diag_input.trace,
                    diag_input.frame,
                    diag_input.meta,
                    market_ppd_params,
                    credible_mass=diag_input.credible_mass,
                    named_event_fit_inputs=diag_input.named_event_fit_inputs,
                )
            else:
                shared_ppd_params = extract_posterior_params(
                    diag_input.trace, diag_input.meta
                )
                ppd_df = posterior_predictive_metric_distributions(
                    diag_input.trace,
                    diag_input.frame,
                    diag_input.meta,
                    shared_ppd_params,
                    credible_mass=diag_input.credible_mass,
                    named_event_fit_inputs=diag_input.named_event_fit_inputs,
                )
            ppd_sec = DiagnosticSection(
                status="computed", payload=ppd_df.to_dict(orient="records")
            )
        except Exception as exc:
            errors.append(f"Posterior predictive metric distributions failed: {exc}")
            ppd_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))

        # --- 3. PPC coverage (single authoritative calculation) ---
        ppc_sec: DiagnosticSection
        ppc_details = None
        mean_ppc = float("nan")
        try:
            ppc_details = posterior_predictive_coverage(
                diag_input.trace,
                diag_input.frame,
                diag_input.meta,
                credible_mass=diag_input.credible_mass,
                predictive_replications=diag_input.predictive_replications,
                random_seed=diag_input.random_seed,
            )
            mean_ppc = float(ppc_details["coverage_pct"].mean())
            ppc_sec = DiagnosticSection(
                status="computed", payload=ppc_details.to_dict(orient="records")
            )
        except Exception as exc:
            errors.append(f"PPC coverage failed: {exc}")
            ppc_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))

        # --- 4. Curve plausibility (single authoritative calculation) ---
        plaus_sec: DiagnosticSection
        plausibility: List[Dict[str, str]] = []
        try:
            if diag_input.model_type == "market_specific":
                plausibility = curve_plausibility_checks_market_specific(
                    diag_input.trace,
                    diag_input.meta,
                    diag_input.frame,
                    roi_bounds=diag_input.roi_bounds,
                )
            else:
                plausibility = curve_plausibility_checks(
                    diag_input.trace,
                    diag_input.meta,
                    diag_input.frame,
                    roi_bounds=diag_input.roi_bounds,
                )
            for issue in plausibility:
                warnings.append(
                    f"[{issue.get('level', 'info')}] "
                    f"{issue.get('channel', '?')}: {issue.get('message', '')}"
                )
            plaus_sec = DiagnosticSection(
                status="computed",
                payload=plausibility,
            )
        except Exception as exc:
            warnings.append(f"Plausibility checks failed: {exc}")
            plaus_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))

        # --- 5. Identification: correlation matrix, condition number and
        # the combined flag report (single authoritative calculation - the
        # only place these three signals are computed; a leave-one-channel-
        # out refit sensitivity check is not included here, since it needs
        # a full model refit per channel and has no place in a single-pass
        # evaluate() call) ---
        ident_sec: DiagnosticSection
        try:
            corr_df = channel_spend_correlation_matrix(
                diag_input.frame, diag_input.meta
            )
            condition_number = design_matrix_condition_number(diag_input.frame)
            id_flags = identification_report(
                diag_input.frame, diag_input.meta, diag_input.trace
            )
            for flag in id_flags:
                warnings.append(
                    f"[{flag.get('level', 'info')}] "
                    f"{flag.get('channel', '?')}: {flag.get('message', '')}"
                )
            ident_sec = DiagnosticSection(
                status="computed",
                payload={
                    "flags": id_flags,
                    "correlation_matrix": json.loads(corr_df.to_json(orient="index")),
                    # Stored as a JSON-safe string when infinite (a
                    # deliberate, meaningful value for a degenerate design
                    # matrix - see design_matrix_condition_number's
                    # docstring - not an error to hide), matching how it is
                    # already displayed.
                    "condition_number": condition_number
                    if condition_number != float("inf")
                    else "inf",
                },
            )
        except Exception as exc:
            errors.append(f"Identification diagnostics failed: {exc}")
            ident_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))

        # --- 6. Coefficient stability (single authoritative calculation) ---
        stab_sec: DiagnosticSection
        try:
            stability_df = posterior_coefficient_stability(
                diag_input.trace, diag_input.meta
            )
            stab_sec = DiagnosticSection(
                status="computed",
                payload=stability_df.to_dict(orient="records"),
            )
        except Exception as exc:
            errors.append(f"Coefficient stability computation failed: {exc}")
            stab_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))

        # --- 7. Backtest ---
        bt_sec: DiagnosticSection
        backtest_results = None
        if diag_input.backtest_folds > 0 and diag_input.fit_fold_fn is not None:
            bt_df = diag_input.raw_model_dataframe
            if bt_df is None:
                bt_df = (
                    diag_input.frame
                    if isinstance(diag_input.frame, pd.DataFrame)
                    else None
                )
            if bt_df is None:
                bt_sec = DiagnosticSection(
                    status="failed",
                    payload=None,
                    error="Backtest requested but no raw DataFrame available.",
                )
            elif diag_input.raw_model_spec is None:
                bt_sec = DiagnosticSection(
                    status="failed",
                    payload=None,
                    error=(
                        "Backtest requested but no ModelSpec available "
                        "(raw_model_spec is required; FHModelMeta has no "
                        "date_col and cannot substitute for it)."
                    ),
                )
            else:
                try:
                    backtest_results = expanding_window_backtest(
                        bt_df,
                        diag_input.raw_model_spec,
                        diag_input.fit_fold_fn,
                        n_folds=diag_input.backtest_folds,
                        min_train_frac=diag_input.min_train_frac,
                    )
                    bt_sec = DiagnosticSection(
                        status="computed",
                        payload=backtest_results.to_dict(orient="records"),
                    )
                except Exception as exc:
                    bt_sec = DiagnosticSection(
                        status="failed", payload=None, error=str(exc)
                    )
        else:
            bt_sec = DiagnosticSection(
                status="not_computed",
                payload=None,
                error="Backtest not requested (backtest_folds <= 0 or no fit_fold_fn).",
            )

        # --- 8. Market x channel engine-capability (REQ-COVERAGE-001 S6,
        # Work Package B) - a deterministic, cheap check computed inline
        # (unlike prior_predictive/predictive_density, which need an
        # explicit separately-triggered MCMC-adjacent run). Requires both a
        # raw ModelSpec (for spec.markets/spec.channels) and a coverage
        # matrix; either being absent leaves this not_applicable rather than
        # assuming support - "no coverage matrix" must never read as "no
        # problem" (mirrors check_market_channel_capability's own
        # coverage_matrix=None handling). ---
        capability_sec: DiagnosticSection
        if diag_input.raw_model_spec is None:
            capability_sec = DiagnosticSection(
                status="not_applicable",
                payload=None,
                error="No ModelSpec available (raw_model_spec is required "
                "to know which markets/channels to check).",
            )
        else:
            try:
                capability_result = check_market_channel_capability(
                    diag_input.raw_model_spec.markets,
                    diag_input.raw_model_spec.channels,
                    diag_input.coverage_matrix,
                )
                capability_payload = capability_result.to_dict()
                # Freshness override (review finding): a per-cell "supported"
                # result is only trustworthy if the coverage matrix was
                # actually built against the joined data currently being
                # fit. Absent or mismatched fingerprints force unsupported,
                # regardless of what check_market_channel_capability itself
                # reported - never silently trusted as "no problem" the way
                # REQ-COVERAGE-001 forbids elsewhere. Only matters when the
                # raw result would otherwise be supported; an already-
                # unsupported result stays unsupported either way.
                is_stale = (
                    diag_input.coverage_matrix is not None
                    and capability_payload["supported"]
                    and (
                        not diag_input.coverage_matrix_built_against_fingerprint
                        or not diag_input.joined_dataframe_fingerprint
                        or diag_input.coverage_matrix_built_against_fingerprint
                        != diag_input.joined_dataframe_fingerprint
                    )
                )
                if is_stale:
                    capability_payload = {
                        **capability_payload,
                        "supported": False,
                        "stale": True,
                        "issues": [
                            {
                                "market": "*",
                                "channel": "*",
                                "reason": (
                                    "Coverage matrix freshness could not be "
                                    "verified against the current joined "
                                    "data (built_against_fingerprint="
                                    f"{diag_input.coverage_matrix_built_against_fingerprint!r}, "
                                    "current="
                                    f"{diag_input.joined_dataframe_fingerprint!r}) "
                                    "- rebuild the coverage matrix on the "
                                    "Data Coverage page."
                                ),
                            }
                        ],
                    }
                else:
                    capability_payload = {**capability_payload, "stale": False}
                capability_sec = DiagnosticSection(
                    status="computed",
                    payload=capability_payload,
                )
            except Exception as exc:
                errors.append(f"Market x channel capability check failed: {exc}")
                capability_sec = DiagnosticSection(
                    status="failed", payload=None, error=str(exc)
                )

        # --- 9. Candidate A Search capacity evidence (REQ-SEARCH-002, Work
        # Package 3) - a deterministic, cheap check computed inline from
        # the already-fitted trace (unlike prior_predictive/
        # predictive_density, which need a fresh model rebuild + sampling).
        # not_applicable for every ordinary (non-Candidate-A) fit;
        # spec/identification/use-gate evidence is included only when a
        # SearchCandidateASpec is supplied - no UI collects one into
        # session state yet (see REPO_REVIEW_AND_NEXT_STEPS.md), so today
        # this section reports the posterior-summary evidence only, with an
        # explicit note that spec-level evidence is unavailable. ---
        search_capacity_sec: DiagnosticSection
        if diag_input.meta.causal_graph_engine != SEARCH_CANDIDATE_A_ENGINE:
            search_capacity_sec = DiagnosticSection(
                status="not_applicable",
                payload=None,
                error="This fit did not use the Candidate A Search engine.",
            )
        else:
            try:
                summary = extract_candidate_a_search_posterior_summary(
                    diag_input.trace, diag_input.meta.outcome_ids
                )
                payload: Dict[str, Any] = {
                    "engine": SEARCH_CANDIDATE_A_ENGINE,
                    "posterior_summary": summary.to_dict(),
                }
                section_warnings: List[str] = []
                if summary.reconciliation_max_abs_error > 1e-3:
                    section_warnings.append(
                        "Posterior-mean reconciliation error "
                        f"({summary.reconciliation_max_abs_error:.4g}) exceeds "
                        "the 1e-3 tolerance - captured + unmet demand does not "
                        "closely track latent demand at the posterior mean."
                    )
                if summary.rhat_max > 1.05 or not np.isfinite(summary.rhat_max):
                    section_warnings.append(
                        f"Candidate A parameter r-hat_max={summary.rhat_max:.3g} "
                        "indicates possible non-convergence for the Search "
                        "demand/capture chain specifically."
                    )
                if diag_input.candidate_a_spec is not None:
                    spec_issues = validate_candidate_a_spec(
                        diag_input.candidate_a_spec,
                        diag_input.candidate_a_search_objects,
                    )
                    identification = identify_candidate_a_search(
                        diag_input.candidate_a_paid_search_cap
                        if diag_input.candidate_a_paid_search_cap is not None
                        else np.array([]),
                        diag_input.candidate_a_paid_search_delivery
                        if diag_input.candidate_a_paid_search_delivery is not None
                        else np.array([]),
                        cap_provenance=diag_input.candidate_a_spec.cap_provenance,
                        cap_mapping_resolved=not spec_issues,
                        capture_mappings_resolved=not spec_issues,
                    )
                    use_gate = candidate_a_use_gate(
                        diag_input.candidate_a_spec, identification
                    )
                    payload["spec_issues"] = list(spec_issues)
                    payload["identification"] = identification.to_dict()
                    payload["use_gate"] = use_gate.to_dict()
                else:
                    payload["spec_issues"] = None
                    payload["identification"] = None
                    payload["use_gate"] = None
                    section_warnings.append(
                        "No Candidate A SearchCandidateASpec was supplied to "
                        "this diagnostics run - spec validation, "
                        "identification, and official-use-gate evidence are "
                        "unavailable; only posterior-summary evidence is "
                        "reported."
                    )
                search_capacity_sec = DiagnosticSection(
                    status="computed",
                    payload=payload,
                    warnings=tuple(section_warnings),
                )
            except Exception as exc:
                errors.append(f"Candidate A Search capacity diagnostics failed: {exc}")
                search_capacity_sec = DiagnosticSection(
                    status="failed", payload=None, error=str(exc)
                )

        # --- 10. Estimand-specific graphical identification
        # (REQ-IDENT-001, Work Package 2) - cheap (no PyMC, pure
        # networkx.DiGraph analysis), computed only when the caller
        # supplies both a `causal_graph` and at least one identification
        # request; `not_computed` (never fabricated) otherwise. Every
        # result carries `GRAPHICAL_IDENTIFICATION_DISCLAIMER` unchanged
        # (REQ-IDENT-001 requirement 1) - this module never strips or
        # paraphrases it. A `direct` effect_type request is passed through
        # unchanged to `assess_backdoor_identification`, which itself
        # returns `unsupported_by_current_checker` rather than silently
        # applying the total-effect criterion (REQ-IDENT-001's own
        # contract; never re-implemented or bypassed here). ---
        graphical_identification_sec: DiagnosticSection
        if diag_input.causal_graph is None or not diag_input.identification_requests:
            graphical_identification_sec = DiagnosticSection(
                status="not_computed",
                payload=None,
                error="No causal_graph and/or identification_requests were "
                "supplied for this evaluation.",
            )
        else:
            try:
                identification_results = []
                for request in diag_input.identification_requests:
                    result = assess_backdoor_identification(
                        diag_input.causal_graph,
                        treatment=request["treatment"],
                        outcome=request["outcome"],
                        proposed_adjustment_set=tuple(
                            request.get("proposed_adjustment_set") or ()
                        ),
                        effect_type=request.get("effect_type", EFFECT_TYPE_TOTAL),
                    )
                    identification_results.append(result.to_dict())
                graphical_identification_sec = DiagnosticSection(
                    status="computed",
                    payload={"results": identification_results},
                )
            except Exception as exc:
                errors.append(f"Graphical identification assessment failed: {exc}")
                graphical_identification_sec = DiagnosticSection(
                    status="failed", payload=None, error=str(exc)
                )

        # --- 11. Latent-state scale/location identification
        # (REQ-LATENT-001, Work Package 2) - dispatched the same way
        # search_capacity is above: `not_applicable` for a fit with no
        # latent causal state at all. For a Candidate A fit, the latent
        # branded-search-demand state (`CANDIDATE_A_LATENT_DEMAND_STATE_
        # ID`) is always assessed - with no declaration supplied, this
        # correctly resolves to `not_identified` (REQ-LATENT-001's
        # fail-closed contract: Requirement 1 is directly unmet), never a
        # fabricated pass. Any additional caller-declared latent states
        # are assessed alongside it. ---
        latent_state_identification_sec: DiagnosticSection
        try:
            declarations_by_id = {
                d.latent_state_id: d for d in diag_input.latent_state_declarations
            }
            candidate_latent_state_ids = set(declarations_by_id)
            if diag_input.meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE:
                candidate_latent_state_ids.add(CANDIDATE_A_LATENT_DEMAND_STATE_ID)

            if not candidate_latent_state_ids:
                latent_state_identification_sec = DiagnosticSection(
                    status="not_applicable",
                    payload=None,
                    error="No latent causal states are declared or fitted "
                    "for this model.",
                )
            else:
                latent_results = []
                for latent_state_id in sorted(candidate_latent_state_ids):
                    chain_draws = diag_input.latent_state_chain_draws.get(
                        latent_state_id
                    )
                    latent_result = assess_latent_state_identification(
                        latent_state_id,
                        declarations_by_id.get(latent_state_id),
                        chain_draws=chain_draws,
                    )
                    latent_results.append(latent_result.to_dict())
                latent_state_identification_sec = DiagnosticSection(
                    status="computed", payload={"results": latent_results}
                )
        except Exception as exc:
            errors.append(f"Latent-state identification assessment failed: {exc}")
            latent_state_identification_sec = DiagnosticSection(
                status="failed", payload=None, error=str(exc)
            )

        # --- 12. Experiment provenance / calibrated-vs-uncalibrated
        # comparison (REQ-EXPMODE-001 / REQ-CALIB-001, Work Package 2) -
        # `not_applicable` when the caller supplies neither, since this
        # repository has no experiment-registry or calibration-mechanism
        # persistence/UI wiring yet (both explicitly deferred by their own
        # requirement records to a future Experiment Evidence workflow).
        # Kept as two clearly separated keys under one payload, never
        # merged into one score - REQ-EXPMODE-001's "never collapsed into
        # an average" and REQ-CALIB-001's "no aggregate/verdict field"
        # both remain enforced by the underlying `to_dict()` calls this
        # section reuses unchanged. ---
        experiment_calibration_sec: DiagnosticSection
        if (
            diag_input.experiment_provenance_report is None
            and diag_input.calibration_comparison_artefact is None
        ):
            experiment_calibration_sec = DiagnosticSection(
                status="not_applicable",
                payload=None,
                error="No experiment evidence or calibrated-model "
                "comparison was supplied for this project.",
            )
        else:
            try:
                experiment_calibration_sec = DiagnosticSection(
                    status="computed",
                    payload={
                        "experiments": (
                            diag_input.experiment_provenance_report.to_dict()
                            if diag_input.experiment_provenance_report is not None
                            else None
                        ),
                        "calibration_comparison": (
                            diag_input.calibration_comparison_artefact.to_dict()
                            if diag_input.calibration_comparison_artefact is not None
                            else None
                        ),
                    },
                )
            except Exception as exc:
                errors.append(
                    f"Experiment / calibration comparison evidence failed: {exc}"
                )
                experiment_calibration_sec = DiagnosticSection(
                    status="failed", payload=None, error=str(exc)
                )

        # --- Build fingerprinted artefact ---
        identity_fp = (
            diag_input.model_identity.fingerprint()
            if diag_input.model_identity is not None
            else ""
        )

        artefact = DiagnosticsArtefact(
            artefact_id=uuid.uuid4().hex,
            diagnostics_version=CURRENT_DIAGNOSTICS_VERSION,
            schema_version=CURRENT_DIAGNOSTICS_SCHEMA_VERSION,
            model_identity_fingerprint=identity_fp,
            evaluated_at=datetime.now(timezone.utc),
            model_type=diag_input.model_type,
            convergence=convergence_sec,
            in_sample_fit=fit_sec,
            posterior_predictive=ppc_sec,
            plausibility=plaus_sec,
            identification=ident_sec,
            coefficient_stability=stab_sec,
            backtest=bt_sec,
            error_metrics=error_metrics_sec,
            residual_diagnostics=residual_diagnostics_sec,
            residual_series=residual_series_sec,
            market_channel_capability=capability_sec,
            search_capacity=search_capacity_sec,
            posterior_predictive_metric_distributions=ppd_sec,
            graphical_identification=graphical_identification_sec,
            latent_state_identification=latent_state_identification_sec,
            experiment_calibration=experiment_calibration_sec,
            global_warnings=tuple(warnings),
            global_errors=tuple(errors),
            settings=(
                ("credible_mass", str(diag_input.credible_mass)),
                ("predictive_replications", str(diag_input.predictive_replications)),
                ("random_seed", str(diag_input.random_seed)),
                ("model_type", diag_input.model_type),
            ),
            legacy_incomplete=False,
        )

        # Assemble the displayed scorecard from the same canonical sections
        # computed above - never a separate compute_scorecard() call, so the
        # displayed values and the artefact's values can never diverge.
        scorecard = {
            "convergence": convergence_payload,
            "in_sample_fit": fit_records,
            "ppc_coverage": ppc_details.to_dict(orient="records")
            if ppc_details is not None
            else [],
            "plausibility_flags": plausibility,
        }

        return DiagnosticsResult(
            scorecard=scorecard,
            max_rhat=max_rhat,
            min_ess=min_ess,
            has_divergences=has_div,
            mean_ppc_coverage_pct=mean_ppc,
            ppc_details=ppc_details,
            backtest_results=backtest_results,
            warnings=warnings,
            errors=errors,
            diagnostics_version=CURRENT_DIAGNOSTICS_VERSION,
            diagnostics_artefact=artefact,
        )

    def run_backtest(
        self,
        artefact: DiagnosticsArtefact,
        *,
        raw_model_dataframe: pd.DataFrame,
        raw_model_spec: ModelSpec,
        fit_fold_fn: Callable,
        n_folds: int,
        min_train_frac: float = 0.6,
    ) -> DiagnosticsArtefact:
        """Run an expanding-window backtest and return a new artefact with
        only the ``backtest`` section replaced.

        PR 82B: a pure, immutable update path for the canonical artefact -
        every other already-computed section (convergence, fit, PPC,
        plausibility, identification, coefficient stability) is carried
        over unchanged, never recomputed. Callers must re-evaluate
        readiness against the returned artefact, since its fingerprint
        changes whenever the backtest section changes.
        """
        try:
            backtest_results = expanding_window_backtest(
                raw_model_dataframe,
                raw_model_spec,
                fit_fold_fn,
                n_folds=n_folds,
                min_train_frac=min_train_frac,
            )
            bt_sec = DiagnosticSection(
                status="computed",
                payload=backtest_results.to_dict(orient="records"),
            )
        except Exception as exc:
            bt_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))
        return dataclasses.replace(artefact, backtest=bt_sec)

    def run_prior_predictive_check(
        self,
        artefact: DiagnosticsArtefact,
        *,
        model: pm.Model,
        frame: Dict[str, Any],
        meta: FHModelMeta,
        model_type: str,
        n_samples: int = 500,
        random_seed: Optional[int] = None,
    ) -> DiagnosticsArtefact:
        """Sample `model`'s priors via `core.diagnostics.
        prior_predictive_summary` and return a new artefact with only the
        ``prior_predictive`` section replaced - the same pure, immutable
        update pattern as `run_backtest` above. Every other already-computed
        section is carried over unchanged, never recomputed. Callers must
        re-evaluate readiness against the returned artefact, since its
        fingerprint changes whenever this section changes.

        `model` must be the exact (or an exact governed rebuild of the)
        unfit `pm.Model` this artefact's fit was built from - REQ-VAL-001's
        prior predictive evidence must answer "which model specification
        generated these priors", so the caller is responsible for
        constructing `model` from the same builder, `frame`, `spec`, and
        hyperparameters the fit itself used (see
        `pages/06_Diagnostics.py`). Sampling failure (e.g. a malformed or
        incompatible model) is caught here and reported as an explicit
        ``failed`` section - it never becomes fabricated zero evidence, and
        no prior on `model` is read, changed, or refit by this call.

        Only ``y_obs`` is requested from ``pm.sample_prior_predictive`` -
        every other free variable/Deterministic this model declares (e.g.
        the ``(obs, outcome)``-shaped ``mu``) is left unmaterialised, since
        `core.diagnostics.prior_predictive_summary` only ever reads
        ``y_obs`` and a large multi-market/multi-year model's other
        variables would otherwise be retained in memory for no reason.
        """
        try:
            result = prior_predictive_summary(
                model,
                frame,
                meta,
                n_samples=n_samples,
                random_seed=random_seed,
            )
            pp_sec = DiagnosticSection(
                status="computed",
                payload={
                    "model_type": model_type,
                    "n_samples": result["n_samples"],
                    "random_seed": result["random_seed"],
                    "rows": result["rows"],
                },
                warnings=tuple(result["warnings"]),
            )
        except Exception as exc:
            pp_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))
        return self._upgrade_schema_and_replace(artefact, prior_predictive=pp_sec)

    def record_prior_predictive_failure(
        self, artefact: DiagnosticsArtefact, error: str
    ) -> DiagnosticsArtefact:
        """For a caller-side failure before sampling could even be attempted
        (e.g. `pages/06_Diagnostics.py` failing to rebuild the fit-time
        model structure at all) - same schema-upgrade contract as
        `run_prior_predictive_check`'s own failure path, via the same
        shared helper, so both routes can never diverge."""
        return self._upgrade_schema_and_replace(
            artefact,
            prior_predictive=DiagnosticSection(
                status="failed", payload=None, error=error
            ),
        )

    def run_predictive_density_check(
        self,
        artefact: DiagnosticsArtefact,
        *,
        model: pm.Model,
        trace: az.InferenceData,
        frame: Dict[str, Any],
        meta: FHModelMeta,
        model_type: str,
    ) -> DiagnosticsArtefact:
        """Compute PSIS-LOO/WAIC evidence via `core.diagnostics.
        predictive_density_summary` (post-hoc against the already-fitted
        `trace`, no refit) and return a new artefact with only the
        ``predictive_density`` section replaced - the same pure, immutable
        update pattern as `run_prior_predictive_check`/`run_backtest`.
        Every other already-computed section is carried over unchanged.
        Callers must re-evaluate readiness against the returned artefact,
        since its fingerprint changes whenever this section changes.

        `model` has the same "exact fit-time model specification" identity
        contract as `run_prior_predictive_check`'s `model` parameter - see
        that method's docstring. `trace` is the actual fitted posterior
        this artefact's other sections were computed from; it is never
        mutated by this call (`core.diagnostics.predictive_density_summary`
        works on an internal copy). A failure (e.g. a malformed or
        incompatible model/trace pair) is caught here and reported as an
        explicit ``failed`` section - never fabricated zero evidence.
        """
        try:
            result = predictive_density_summary(model, trace, frame, meta)
            pd_sec = DiagnosticSection(
                status="computed",
                payload={
                    "model_type": model_type,
                    "elpd_loo": result["elpd_loo"],
                    "elpd_loo_se": result["elpd_loo_se"],
                    "p_loo": result["p_loo"],
                    "loo_good_k_threshold": result["loo_good_k_threshold"],
                    "elpd_waic": result["elpd_waic"],
                    "elpd_waic_se": result["elpd_waic_se"],
                    "p_waic": result["p_waic"],
                    "n_data_points": result["n_data_points"],
                    "rows": result["rows"],
                },
                warnings=tuple(result["warnings"]),
            )
        except Exception as exc:
            pd_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))
        return self._upgrade_schema_and_replace(artefact, predictive_density=pd_sec)

    def record_predictive_density_failure(
        self, artefact: DiagnosticsArtefact, error: str
    ) -> DiagnosticsArtefact:
        """For a caller-side failure before predictive-density computation
        could even be attempted (e.g. `pages/06_Diagnostics.py` failing to
        rebuild the fit-time model structure at all) - same schema-upgrade
        contract as `run_predictive_density_check`'s own failure path."""
        return self._upgrade_schema_and_replace(
            artefact,
            predictive_density=DiagnosticSection(
                status="failed", payload=None, error=error
            ),
        )

    def run_historical_and_structural_validation_check(
        self,
        artefact: DiagnosticsArtefact,
        *,
        results_df: pd.DataFrame,
        folds: Sequence[ValidationFold],
        assessments: Sequence[FoldReconstructionAssessment],
        snapshots: Sequence[FoldParameterSnapshot],
        reconstruction_tier: Optional[str] = RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY,
    ) -> DiagnosticsArtefact:
        """Populate `historical_validation` (REQ-LEAK-001) and
        `structural_stability` (REQ-STAB-001) together from one real
        fold-refit run, and return a new artefact with only those two
        sections replaced - the same pure, immutable update pattern as
        `run_backtest`/`run_prior_predictive_check`/`run_predictive_
        density_check`. Every other already-computed section is carried
        over unchanged.

        Callers obtain `results_df`/`folds`/`assessments`/`snapshots` from
        exactly one call to `application.fold_refit_service.
        run_leakage_safe_fold_refit` or `run_leakage_safe_fold_refit_
        from_sources` (its `LeakageSafeFoldRefitResult`'s own four fields,
        by name) - this method is deliberately decoupled from that
        module's own result type (accepting the plain `core.
        validation_folds`/`core.structural_stability` types instead) so
        this service does not need to import the heavier fold-refit-
        service module. Real per-fold PyMC re-fitting is expensive and is
        never performed by this method itself - mirroring `core.
        structural_stability`'s and `core.validation_folds`'s own "the
        caller supplies the fold-local computation" contract.

        `reconstruction_tier` (one of `core.validation_folds.
        RECONSTRUCTION_TIERS`) records which reconstruction produced the
        supplied evidence - `source_version_aware_fold_local` for a
        `run_leakage_safe_fold_refit_from_sources` run, or
        `coverage_metadata_only` for a `run_leakage_safe_fold_refit` run.
        It defaults to the *weaker* `coverage_metadata_only` tier: a
        caller that produced the deeper tier must say so explicitly, never
        by omission. It is stored in the `historical_validation` payload
        and therefore enters the artefact fingerprint - the same evidence
        can never be re-labelled a stronger tier without changing the
        fingerprint, and an unknown value fails closed here rather than
        being recorded. `from_dict` restores the same weaker default for
        stored artefacts that predate the tier contract, never a stronger
        one.

        `historical_validation` is `computed` whenever at least one fold
        was assessed (even if every fold was rejected - that is itself
        genuine evidence, never `not_computed`), `not_computed` only when
        the caller passes no folds at all. `structural_stability` requires
        at least one real per-fold snapshot (REQ-LEAK-001 requirement 6:
        both sections share one notion of what a historical fold is, so a
        fold rejected by the leakage-safety assessment never contributes a
        snapshot to either section) - with zero snapshots, it is
        `not_computed` with an explicit reason, never a fabricated
        artefact from `core.structural_stability.assess_structural_
        stability` (which itself raises on an empty snapshot tuple).
        """
        if reconstruction_tier is not None and reconstruction_tier not in (
            RECONSTRUCTION_TIERS
        ):
            raise ValueError(
                f"Unknown reconstruction_tier {reconstruction_tier!r} - "
                f"expected one of {RECONSTRUCTION_TIERS!r}."
            )
        if not folds:
            historical_validation_sec = DiagnosticSection(
                status="not_computed",
                payload=None,
                error="No validation folds were supplied for this evaluation.",
            )
        else:
            try:
                historical_validation_payload: Dict[str, Any] = {
                    "folds": [f.to_dict() for f in folds],
                    "assessments": [a.to_dict() for a in assessments],
                    "results": results_df.to_dict(orient="records"),
                    "n_folds_assessed": len(folds),
                    "n_folds_leakage_safe": sum(
                        1 for a in assessments if a.is_leakage_safe
                    ),
                }
                if reconstruction_tier is not None:
                    historical_validation_payload["reconstruction_tier"] = (
                        reconstruction_tier
                    )
                historical_validation_sec = DiagnosticSection(
                    status="computed",
                    payload=historical_validation_payload,
                )
            except Exception as exc:
                historical_validation_sec = DiagnosticSection(
                    status="failed", payload=None, error=str(exc)
                )

        if not snapshots:
            structural_stability_sec = DiagnosticSection(
                status="not_computed",
                payload=None,
                error="No fold cleared leakage-safety/official-preparation "
                "assessment with a real per-fold parameter snapshot - "
                "structural-stability comparison requires at least one.",
            )
        else:
            try:
                stability_artefact = assess_structural_stability(tuple(snapshots))
                structural_stability_sec = DiagnosticSection(
                    status="computed", payload=stability_artefact.to_dict()
                )
            except Exception as exc:
                structural_stability_sec = DiagnosticSection(
                    status="failed", payload=None, error=str(exc)
                )

        return self._upgrade_schema_and_replace(
            artefact,
            historical_validation=historical_validation_sec,
            structural_stability=structural_stability_sec,
        )

    def record_historical_and_structural_validation_failure(
        self, artefact: DiagnosticsArtefact, error: str
    ) -> DiagnosticsArtefact:
        """For a caller-side failure before fold reconstruction/re-fitting
        could even be attempted (e.g. a page failing to build the folds at
        all - `application.fold_refit_service.run_leakage_safe_fold_refit`
        raising before it ever returns a `LeakageSafeFoldRefitResult` for
        `run_historical_and_structural_validation_check` to consume) - same
        schema-upgrade contract as `record_prior_predictive_failure`/
        `record_predictive_density_failure`, via the same shared helper, so
        every failure route can never diverge."""
        failed = DiagnosticSection(status="failed", payload=None, error=error)
        return self._upgrade_schema_and_replace(
            artefact,
            historical_validation=failed,
            structural_stability=failed,
        )

    @staticmethod
    def _upgrade_schema_and_replace(
        artefact: DiagnosticsArtefact,
        *,
        prior_predictive: Optional[DiagnosticSection] = None,
        predictive_density: Optional[DiagnosticSection] = None,
        historical_validation: Optional[DiagnosticSection] = None,
        structural_stability: Optional[DiagnosticSection] = None,
    ) -> DiagnosticsArtefact:
        """Replace one or more of `prior_predictive`, `predictive_density`,
        `historical_validation`, `structural_stability` on `artefact` and,
        if `artefact` predates the current schema (computed before those
        sections existed, or just restored from an older imported bundle),
        upgrade its `schema_version`/`diagnostics_version` to current at
        the same time. Explicit named parameters (never a generic
        `**kwargs` splat into `dataclasses.replace`) so mypy can verify
        each argument against `DiagnosticsArtefact`'s actual field types.

        Without this, `dataclasses.replace` alone would leave an older
        artefact's `schema_version` unchanged while it now carries real
        evidence in a section that schema version doesn't recognise - an
        internally inconsistent object that `to_dict()`/`from_dict()`
        cannot round-trip: `from_dict` reads the (unchanged, pre-upgrade)
        `schema_version` and treats the new section as unavailable for that
        schema, discarding the evidence this call just added (Codex review,
        PR #147). Every code path that replaces any of these four sections
        - computed or failed - must go through this helper, never a bare
        `dataclasses.replace(artefact, ...)`.
        """
        schema_version = max(
            artefact.schema_version, CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        )
        diagnostics_version = (
            CURRENT_DIAGNOSTICS_VERSION
            if schema_version > artefact.schema_version
            else artefact.diagnostics_version
        )
        return dataclasses.replace(
            artefact,
            schema_version=schema_version,
            diagnostics_version=diagnostics_version,
            prior_predictive=(
                prior_predictive
                if prior_predictive is not None
                else artefact.prior_predictive
            ),
            predictive_density=(
                predictive_density
                if predictive_density is not None
                else artefact.predictive_density
            ),
            historical_validation=(
                historical_validation
                if historical_validation is not None
                else artefact.historical_validation
            ),
            structural_stability=(
                structural_stability
                if structural_stability is not None
                else artefact.structural_stability
            ),
        )

    @staticmethod
    def _check_convergence(trace: az.InferenceData) -> tuple[float, float, int]:
        """Extract raw convergence metrics from the trace: max R-hat, min
        ESS, and the divergence count (0 if no divergences or no
        sample_stats) - the single authoritative convergence calculation
        reused for both the artefact and the displayed scorecard."""
        # A degenerate/zero-variance chain makes ArviZ's own rank-normalised
        # R-hat divide 0/0 internally (arviz/stats/diagnostics.py) - see
        # ancestry_mmm/core/models.py's compute_model_diagnostics for the
        # full rationale. Suppressed only around this exact call.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="invalid value encountered in scalar divide",
                category=RuntimeWarning,
            )
            rhat = az.rhat(trace, var_names=["mu", "beta", "hill_K", "alpha"])
        ess = az.ess(trace, var_names=["mu", "beta", "hill_K", "alpha"])

        max_rhat = float("-inf")
        for var_data in rhat.values():
            if hasattr(var_data, "values"):
                max_rhat = max(max_rhat, float(var_data.values.max()))

        min_ess = float("inf")
        for var_data in ess.values():
            if hasattr(var_data, "values"):
                min_ess = min(min_ess, float(var_data.values.min()))

        divergence_count = 0
        if hasattr(trace, "sample_stats") and "diverging" in trace.sample_stats:
            divergence_count = int(trace.sample_stats["diverging"].values.sum())

        return max_rhat, min_ess, divergence_count
