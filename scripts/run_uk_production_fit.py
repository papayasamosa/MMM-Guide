"""Run the approved local UK production-readiness PyMC fits.

This is a batch entry point for the real UK source pack.  It deliberately
keeps the official preparation gate, model construction, and sampling in one
framework-independent process so a Streamlit session is not the system of
record.  Raw workbooks are read only; run artefacts are written outside Git.

The runner fits two separate shared/hierarchical PyMC models:

* Family History NBT: New, DNA cross-sell, and Winback jointly;
* DNA kit sale: New Customer and Existing Family History Customer jointly.

Branded paid search and the incomplete DNA Performance Social series remain
retained in the source pack but are excluded from the official fitted inputs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import arviz as az
import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ancestry_mmm.application.uk_readiness import run_uk_readiness  # noqa: E402
from ancestry_mmm.core.coverage import (  # noqa: E402
    FrequencyMetadata,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.frequency_alignment import assess_official_preparation  # noqa: E402
from ancestry_mmm.core.hierarchical_model import FHModelMeta  # noqa: E402
from ancestry_mmm.core.market_data_capability import ENGINE_PYMC_RECTANGULAR  # noqa: E402
from ancestry_mmm.core.models import compute_model_diagnostics, fit_model  # noqa: E402
from ancestry_mmm.core.net_billthrough import (  # noqa: E402
    NBT_METRIC_KEY,
    NetBillthroughCompletenessMetadata,
)
from ancestry_mmm.core.official_preparation import (  # noqa: E402
    build_official_capability_report,
    prepare_canonical_native_frame,
)
from ancestry_mmm.core.schema import ModelSpec  # noqa: E402
from ancestry_mmm.data.loader import load_standard_workbook_with_source_version  # noqa: E402
from ancestry_mmm.data.source_pack_adoption import (  # noqa: E402
    adopted_model_input_sources,
    adopt_standard_source_bundle,
)
from ancestry_mmm.data.templates import canonicalize_standard_workbook  # noqa: E402
from ancestry_mmm.data.preprocessor import prepare_fh_modeling_frame  # noqa: E402


DEFAULT_PACK_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\uk-readiness\approved-uk-packs-20260820-v3"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\uk-readiness\production-fit-20260820"
)
GOVERNED_START = "2023-01-01"
GOVERNED_END = "2025-06-29"
MATURITY_CUTOFF = "2025-07-13"
TARGET_FREQUENCY = "weekly"
NBT_MATURITY_POLICY = (
    "Cohort is complete once 14 days have elapsed after signup; this is a "
    "completeness horizon, not a fixed NBT event lag."
)


class FitGateError(RuntimeError):
    """Raised when official preparation cannot authorise a specific fit."""


class _Upload:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = path.name

    def getvalue(self) -> bytes:
        return self.path.read_bytes()


@dataclass(frozen=True)
class LoadedPack:
    adoption: Any
    bundles: tuple[Any, ...]
    versions: Mapping[str, tuple[str, int]]
    source_evidence: tuple[dict[str, Any], ...]
    outcome_bundle: Any
    activity_bundle: Any


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.bool_, np.integer, np.floating)):
        return value.item()
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"Cannot serialise {type(value).__name__}")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )


def _load_pack(pack_dir: Path) -> LoadedPack:
    files = {
        "activity_and_media": pack_dir
        / "activity_data_approved_metadata_and_structural_zeros.xlsx",
        "context_and_external_factors": pack_dir
        / "context_and_external_factors_data_native_preserved.xlsx",
        "outcomes": pack_dir / "outcome_data_approved_registry.xlsx",
    }
    adoption = None
    bundles: list[Any] = []
    versions: dict[str, tuple[str, int]] = {}
    evidence: list[dict[str, Any]] = []
    outcome_bundle = None
    activity_bundle = None
    for domain, path in files.items():
        if not path.exists():
            raise FitGateError(f"Required source workbook is missing: {path}")
        workbook, version, error = load_standard_workbook_with_source_version(
            _Upload(path),
            source_id=f"uk-production-{domain}",
            logical_domain=domain,
        )
        if error or workbook is None or version is None:
            raise FitGateError(f"Could not load {domain}: {error}")
        bundle = canonicalize_standard_workbook(workbook)
        bundles.append(bundle)
        versions[domain] = (version.source_id, version.version)
        evidence.append(
            {
                "domain": domain,
                "source_id": version.source_id,
                "version": version.version,
                "checksum": version.checksum,
                "filename": version.original_filename,
                "size_bytes": version.size_bytes,
            }
        )
        if domain == "outcomes":
            outcome_bundle = bundle
        elif domain == "activity_and_media":
            activity_bundle = bundle
        adoption = adopt_standard_source_bundle(
            bundle,
            activity_definitions=adoption.activity_definitions if adoption else (),
            activity_model_input=(
                adoption.activity_model_input if adoption else None
            ),
            outcome_data=adoption.outcome_data if adoption else None,
            context_data=adoption.context_data if adoption else None,
            context_variable_metadata=(
                adoption.context_variable_metadata if adoption else ()
            ),
            experiment_evidence=adoption.experiment_evidence if adoption else None,
            semantic_statuses=adoption.semantic_statuses if adoption else (),
        )
    if adoption is None or outcome_bundle is None or activity_bundle is None:
        raise FitGateError("The three required source domains were not adopted.")
    return LoadedPack(
        adoption=adoption,
        bundles=tuple(bundles),
        versions=versions,
        source_evidence=tuple(evidence),
        outcome_bundle=outcome_bundle,
        activity_bundle=activity_bundle,
    )


def _source_only_gate(
    pack: LoadedPack, pack_dir: Path, output_dir: Path
) -> dict[str, Any]:
    report = run_uk_readiness(
        source_paths=(
            ("activity_and_media", pack_dir / "activity_data_approved_metadata_and_structural_zeros.xlsx"),
            ("context_and_external_factors", pack_dir / "context_and_external_factors_data_native_preserved.xlsx"),
            ("outcomes", pack_dir / "outcome_data_approved_registry.xlsx"),
        ),
        output_dir=output_dir / "source-readiness",
        governed_start=GOVERNED_START,
        governed_end=GOVERNED_END,
        governed_frequency=TARGET_FREQUENCY,
    )
    stages = {stage.name: stage for stage in report.stages}
    required = (
        "source_domain_schema",
        "source_version_identity",
        "semantic_adoption",
        "calendar_coverage_preparation",
    )
    blockers = [
        f"{name}: {stages[name].summary}"
        for name in required
        if name not in stages or stages[name].status != "pass"
    ]
    if blockers:
        raise FitGateError(
            "Source readiness gate failed before model-specific preparation: "
            + "; ".join(blockers)
        )
    return {
        "status": report.status,
        "report_path": str(report.report_path),
        "stages": {
            name: {
                "status": stage.status,
                "summary": stage.summary,
                "elapsed_seconds": stage.elapsed_seconds,
            }
            for name, stage in stages.items()
        },
    }


def _check_sampling_runtime() -> None:
    """Fail closed when the approved NUTS path has no viable local runtime.

    The pinned PyMC path uses PyTensor's compiled scan/log-gradient support.
    On Windows, this environment has neither a C++ compiler nor an installed
    JAX/NumPyro backend.  A small empirical smoke run took 271 seconds for
    six NUTS steps, so starting the approved default run here would be an
    unbounded multi-day operation rather than a responsible production fit.
    """
    has_cpp = any(shutil.which(command) for command in ("g++", "clang++", "cl"))
    has_jax_backend = bool(
        importlib.util.find_spec("jax")
        and importlib.util.find_spec("numpyro")
    )
    if not has_cpp and not has_jax_backend:
        raise FitGateError(
            "Approved PyMC NUTS fit is runtime-blocked on this Windows host: "
            "no C++ compiler is available for PyTensor and no JAX/NumPyro "
            "backend is installed. The existing production sampler remains "
            "unchanged; install a supported compiler/backend in the execution "
            "environment and rerun. A smoke run required 271 seconds for only "
            "six NUTS steps, so the full default run was not started."
        )


def _completeness_metadata(outcomes: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """Create a run-level integrity record from the approved source policy.

    The supplied workbook's dictionary carries the approved 14-day policy but
    does not contain an ``outcome_completeness`` sheet.  This record therefore
    binds the requested target window to the approved maturity cutoff; it is
    not presented as a newly observed source date.
    """
    from ancestry_mmm.core.outcome_approval import fingerprint_outcome_definition

    result: dict[str, dict[str, Any]] = {}
    for outcome in outcomes:
        if outcome.metric_key != NBT_METRIC_KEY:
            continue
        result[outcome.outcome_id] = NetBillthroughCompletenessMetadata(
            data_as_of_date=MATURITY_CUTOFF,
            model_start_week=GOVERNED_START,
            model_end_week=GOVERNED_END,
            latest_complete_net_billthrough_week=GOVERNED_END,
            maturity_rule_description=NBT_MATURITY_POLICY,
            source_owner=outcome.business_owner,
            outcome_id=outcome.outcome_id,
            definition_version=outcome.definition_version,
            definition_fingerprint=fingerprint_outcome_definition(outcome),
        ).to_dict()
    return result


def _coverage_matrix(
    frame: pd.DataFrame,
    *,
    variables: Sequence[str],
    outcome_columns: Sequence[str],
    versions: Mapping[str, tuple[str, int]],
) -> Any:
    """Build a Sunday-anchored coverage matrix for the governed UK grid.

    The generic coverage helper's historical weekly calendar is Monday-
    anchored.  This run's source contract is explicitly Sunday-Saturday, so
    the fit gate builds the same metadata contract against the already
    resolved Sunday grid rather than manufacturing a different calendar.
    """
    expected_dates = pd.date_range(GOVERNED_START, GOVERNED_END, freq="7D")
    expected_text = tuple(item.strftime("%Y-%m-%d") for item in expected_dates)
    records: list[VariableCoverageRecord] = []
    for variable in variables:
        source_id, source_version = (
            versions["outcomes"]
            if variable in outcome_columns
            else versions["activity_and_media"]
        )
        for market in sorted(frame["market"].astype(str).unique()):
            scoped = frame[frame["market"].astype(str) == market]
            if variable not in scoped.columns:
                raise FitGateError(
                    f"Official coverage is unavailable for consumed variable {variable!r}."
                )
            observed = scoped[variable].notna().to_numpy()
            if len(scoped) != len(expected_dates) or not bool(observed.all()):
                missing_count = int(len(observed) - observed.sum())
                raise FitGateError(
                    f"Official coverage is incomplete for {variable!r} in market "
                    f"{market!r}: {missing_count} missing observation(s) on the "
                    "governed Sunday-Saturday grid; no zero-fill was applied."
                )
            records.append(
                VariableCoverageRecord(
                    variable_id=variable,
                    source_id=source_id,
                    source_version=source_version,
                    market=market,
                    frequency=FrequencyMetadata(
                        native_frequency="weekly",
                        target_frequency="weekly",
                        variable_class="flow_count",
                    ),
                    coverage_segments=(),
                    observed_start=expected_text[0],
                    observed_end=expected_text[-1],
                    expected_start=expected_text[0],
                    expected_end=expected_text[-1],
                )
            )
    return VariableCoverageMatrix(
        matrix_id="uk-production-fit-20260820",
        matrix_version=1,
        generated_at="2026-08-20",
        records=tuple(records),
        notes="Sunday-Saturday canonical UK grid; no source missingness was filled.",
    )


def _channels_for_model(
    activities: Sequence[Any],
    *,
    product: str,
    excluded_inputs: set[str],
) -> tuple[list[str], list[str]]:
    selected: list[str] = []
    dna_channels: list[str] = []
    for activity in activities:
        if not activity.applies_to_market("UK"):
            continue
        model_input = activity.resolved_model_input_column
        if model_input in excluded_inputs:
            continue
        advertised = str(activity.product_advertised or "Unspecified")
        if advertised not in {product, "Unspecified"}:
            continue
        if model_input not in selected:
            selected.append(model_input)
        if product == "Family History" and advertised == "DNA":
            dna_channels.append(model_input)
    return selected, dna_channels


def _incomplete_target_inputs(
    activity_data: pd.DataFrame,
) -> dict[str, int]:
    target_dates = pd.date_range(GOVERNED_START, GOVERNED_END, freq="7D")
    target = activity_data.copy()
    target["period_start"] = pd.to_datetime(target["period_start"])
    target = target[target["period_start"].isin(target_dates)]
    incomplete: dict[str, int] = {}
    for column in target.columns:
        if column in {"period_start", "market"}:
            continue
        missing = int(target[column].isna().sum())
        if len(target) != len(target_dates) or missing:
            incomplete[column] = missing + max(len(target_dates) - len(target), 0)
    return incomplete


def _no_target_window_variation(
    activity_data: pd.DataFrame,
) -> list[str]:
    """Identify model-input columns with no estimable target-window variation.

    A complete all-zero (or otherwise constant) delivery series is not a
    usable intervention for the requested fit window.  It remains in the
    retained source pack, but fitting it would leave its response parameters
    prior-driven while increasing sampler geometry risk.  Pre-window history
    is still preserved for the channels that are selected.
    """

    target_dates = pd.date_range(GOVERNED_START, GOVERNED_END, freq="7D")
    target = activity_data.copy()
    target["period_start"] = pd.to_datetime(target["period_start"])
    target = target[target["period_start"].isin(target_dates)]
    unsupported: list[str] = []
    for column in target.columns:
        if column in {"period_start", "market"}:
            continue
        values = pd.to_numeric(target[column], errors="coerce").dropna()
        if values.empty or values.nunique(dropna=True) <= 1:
            unsupported.append(str(column))
    return sorted(unsupported)


def _add_history(
    frame: dict[str, Any],
    activity_data: pd.DataFrame,
    spec: ModelSpec,
) -> dict[str, Any]:
    target_start = pd.Timestamp(GOVERNED_START)
    history = activity_data.copy()
    history[spec.date_col] = pd.to_datetime(history[spec.date_col])
    history = history[history[spec.date_col] < target_start].copy()
    history = history[history[spec.market_col].isin(spec.markets)]
    history = history.sort_values([spec.market_col, spec.date_col]).reset_index(drop=True)
    if history.empty:
        raise FitGateError(
            f"{spec.markets} has no pre-window activity history for adstock carry-in."
        )
    missing = [
        channel
        for channel in spec.channels
        if channel not in history.columns or history[channel].isna().any()
    ]
    if missing:
        raise FitGateError(
            "Historical carry-in is unavailable for selected channel(s): "
            + ", ".join(missing)
        )
    history_bounds: list[tuple[int, int]] = []
    offset = 0
    history_parts = []
    for market in frame["markets"]:
        part = history[history[spec.market_col] == market]
        if part.empty:
            raise FitGateError(
                f"Historical carry-in is unavailable for market {market!r}."
            )
        history_parts.append(part[spec.channels])
        history_bounds.append((offset, offset + len(part)))
        offset += len(part)
    frame["X_media_history"] = pd.concat(history_parts, ignore_index=True).to_numpy(
        dtype=float
    )
    frame["history_market_bounds"] = history_bounds
    return {
        "history_start": history[spec.date_col].min().strftime("%Y-%m-%d"),
        "history_end": history[spec.date_col].max().strftime("%Y-%m-%d"),
        "history_rows": int(len(history)),
    }


def _model_meta_payload(meta: FHModelMeta) -> dict[str, Any]:
    masks = meta.resolved_pathway_masks.to_dict()
    return {
        "markets": meta.markets,
        "outcome_ids": meta.outcome_ids,
        "channels": meta.channels,
        "dna_channels": meta.dna_channels,
        "dna_lag_weeks": meta.dna_lag_weeks,
        "direct_dna_outcome_ids": meta.direct_dna_outcome_ids,
        "control_names": meta.control_names,
        "pathway_masks": masks,
        "causal_graph_engine": meta.causal_graph_engine,
    }


def _posterior_summary(trace: az.InferenceData, path: Path) -> None:
    summary = az.summary(trace, round_to=None)
    summary.to_csv(path)


def _fit_one(
    *,
    name: str,
    frame: dict[str, Any],
    spec: ModelSpec,
    outcomes: Sequence[Any],
    output_dir: Path,
    seed: int,
    draws: int,
    tune: int,
    chains: int,
    target_accept: float,
) -> dict[str, Any]:
    from ancestry_mmm.application.model_fit_service import build_model_for_spec

    started = time.perf_counter()
    model_result = build_model_for_spec(
        frame=frame,
        model_spec=spec,
        model_type="shared",
        dna_lag_weeks=4,
        dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
        prior_config={},
        direct_dna_outcome_ids=(
            list(spec.segment_outcomes.values()) if name == "dna_kit" else None
        ),
        causal_graph=None,
        search_objects=(),
    )
    trace = fit_model(
        model_result.model,
        draws=draws,
        tune=tune,
        chains=chains,
        target_accept=target_accept,
        random_seed=seed,
        cores=1,
    )
    model_dir = output_dir / name
    model_dir.mkdir(parents=True, exist_ok=True)
    trace_path = model_dir / "posterior.nc"
    trace.to_netcdf(trace_path)
    summary_path = model_dir / "posterior_summary.csv"
    _posterior_summary(trace, summary_path)
    diagnostics = compute_model_diagnostics(trace)
    return {
        "status": "fit_completed",
        "validation_status": "pending_diagnostics_review",
        "model_name": name,
        "engine": ENGINE_PYMC_RECTANGULAR,
        "model_type": "shared_hierarchical_model_a",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "observations": int(frame["X_media"].shape[0]),
        "markets": list(frame["markets"]),
        "outcome_ids": list(frame["outcome_ids"]),
        "channels": list(frame["channels"]),
        "history_rows": int(np.asarray(frame["X_media_history"]).shape[0]),
        "trace_path": str(trace_path),
        "posterior_summary_path": str(summary_path),
        "meta": _model_meta_payload(model_result.meta),
        "diagnostics": {
            "rhat_max": diagnostics.get("rhat_max"),
            "ess_min": diagnostics.get("ess_min"),
            "divergences": diagnostics.get("divergences"),
            "converged": diagnostics.get("converged"),
        },
        "sampling": {
            "draws": draws,
            "tune": tune,
            "chains": chains,
            "target_accept": target_accept,
            "seed": seed,
            "cores": 1,
        },
    }


def run(
    *,
    pack_dir: Path,
    output_dir: Path,
    draws: int,
    tune: int,
    chains: int,
    target_accept: float,
    seed: int,
    fit_enabled: bool = True,
    only_model: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pack = _load_pack(pack_dir)
    source_gate = _source_only_gate(pack, pack_dir, output_dir)
    if fit_enabled:
        _check_sampling_runtime()
    sources = adopted_model_input_sources(
        outcome_data=pack.adoption.outcome_data,
        activity_model_input=pack.adoption.activity_model_input,
        context_model_input=pack.adoption.context_data,
        context_variable_metadata=pack.adoption.context_variable_metadata,
    )
    if sources is None:
        raise FitGateError("No adopted source tables are available for official preparation.")

    # The selected proposal consumes only weekly outcomes and activity.  The
    # native monthly/weekly context source remains retained but diagnostic;
    # it is intentionally not converted or placed in the fit.
    canonical = prepare_canonical_native_frame(
        sources,
        date_col="period_start",
        market_col="market",
        governed_start=GOVERNED_START,
        governed_end=GOVERNED_END,
        governed_frequency=TARGET_FREQUENCY,
        consumed_variable_ids=(),
    )
    target = canonical.frame.copy()
    target["period_start"] = pd.to_datetime(target["period_start"])
    governed_dates = pd.date_range(GOVERNED_START, GOVERNED_END, freq="7D")
    target = target[target["period_start"].isin(governed_dates)].copy()
    target = target.sort_values(["market", "period_start"]).reset_index(drop=True)
    if len(target) != len(governed_dates):
        raise FitGateError(
            "The official consumed-input grid does not contain exactly the "
            f"{len(governed_dates)} requested Sunday-Saturday weeks."
        )
    outcome_definitions = list(pack.outcome_bundle.outcome_definitions)
    nbt_metadata_by_outcome = _completeness_metadata(outcome_definitions)
    if len(nbt_metadata_by_outcome) != 3:
        raise FitGateError(
            "The approved Family History NBT definitions did not yield three "
            "run-level completeness records."
        )

    excluded_inputs = {
        "uk_dna_performance_social",
        "uk_fh_brand_search",
        "uk_dna_brand_search",
    }
    incomplete_inputs = _incomplete_target_inputs(
        pack.activity_bundle.model_input_media
    )
    no_target_window_variation = _no_target_window_variation(
        pack.activity_bundle.model_input_media
    )
    excluded_inputs.update(incomplete_inputs)
    excluded_inputs.update(no_target_window_variation)
    activities = list(pack.activity_bundle.activity_definitions)
    fh_channels, fh_dna_channels = _channels_for_model(
        activities, product="Family History", excluded_inputs=excluded_inputs
    )
    dna_channels, _ = _channels_for_model(
        activities, product="DNA", excluded_inputs=excluded_inputs
    )
    if not fh_channels or not dna_channels:
        raise FitGateError("Approved product-specific channel resolution produced an empty model.")

    fh_outcomes = [
        item
        for item in outcome_definitions
        if item.included_in_fit and item.product == "Family History"
    ]
    dna_outcomes = [
        item
        for item in outcome_definitions
        if item.included_in_fit and item.product == "DNA" and item.metric_key == "dna_kit_sale"
    ]
    if len(fh_outcomes) != 3 or len(dna_outcomes) != 2:
        raise FitGateError("Approved outcome registry does not resolve to 3 FH and 2 DNA primary outcomes.")

    model_configs = (
        (
            "family_history",
            fh_outcomes,
            ModelSpec(
                date_col="period_start",
                market_col="market",
                markets=["UK"],
                segment_outcomes={item.segment: item.source_column for item in fh_outcomes},
                channels=fh_channels,
                dna_channels=fh_dna_channels,
                fh_dna_cross_sell_outcome_id="fh_gsa_dna_cross_sell",
                fourier_harmonics=3,
            ),
        ),
        (
            "dna_kit",
            dna_outcomes,
            ModelSpec(
                date_col="period_start",
                market_col="market",
                markets=["UK"],
                segment_outcomes={item.segment: item.source_column for item in dna_outcomes},
                channels=dna_channels,
                # DNA is a separate product model; its DNA-specific media are
                # ordinary direct interventions, not an FH cross-product halo.
                dna_channels=[],
                fourier_harmonics=3,
            ),
        ),
    )
    if only_model is not None:
        valid_model_names = {config[0] for config in model_configs}
        if only_model not in valid_model_names:
            raise ValueError(
                f"Unknown model {only_model!r}; choose one of "
                + ", ".join(sorted(valid_model_names))
            )
        model_configs = tuple(
            config for config in model_configs if config[0] == only_model
        )

    models: list[dict[str, Any]] = []
    model_gate: dict[str, Any] = {}
    for model_name, model_outcomes, spec in model_configs:
        variables = [item.source_column for item in model_outcomes] + list(spec.channels)
        matrix = _coverage_matrix(
            target,
            variables=variables,
            outcome_columns=[item.source_column for item in model_outcomes],
            versions=pack.versions,
        )
        capability = build_official_capability_report(
            spec,
            model_outcomes,
            matrix,
            activity_definitions=activities,
            search_objects=(),
        )
        assessment = assess_official_preparation(
            matrix,
            governed_start=GOVERNED_START,
            governed_end=GOVERNED_END,
            governed_frequency=TARGET_FREQUENCY,
            consumed_variable_ids=tuple(item.variable_id for item in capability.consumed_variables),
            capability_evidence=capability.to_dict(),
        )
        model_gate[model_name] = {
            "status": "pass" if assessment.ready else assessment.status,
            "assessment": assessment.to_dict(),
            "capability": capability.to_dict(),
            "coverage_matrix_fingerprint": matrix.fingerprint(),
            "channels": list(spec.channels),
            "outcome_ids": [item.outcome_id for item in model_outcomes],
        }
        if not assessment.ready:
            raise FitGateError(
                f"Official preparation blocked {model_name}: "
                + "; ".join(assessment.decisions_required or (assessment.reason,))
            )
        frame = prepare_fh_modeling_frame(
            target,
            spec,
            outcomes=model_outcomes,
            activity_definitions=activities,
            net_billthrough_metadata=next(iter(nbt_metadata_by_outcome.values())),
        )
        frame["preparation_mode"] = "official"
        history_evidence = _add_history(
            frame,
            pack.activity_bundle.model_input_media,
            spec,
        )
        model_gate[model_name]["history"] = history_evidence
        try:
            if fit_enabled:
                result = _fit_one(
                    name=model_name,
                    frame=frame,
                    spec=spec,
                    outcomes=model_outcomes,
                    output_dir=output_dir,
                    # Keep the full-run seed assignment stable when a single
                    # model is resumed after the other model has completed.
                    seed=seed + (0 if model_name == "family_history" else 1),
                    draws=draws,
                    tune=tune,
                    chains=chains,
                    target_accept=target_accept,
                )
            else:
                from ancestry_mmm.application.model_fit_service import build_model_for_spec

                proposed = build_model_for_spec(
                    frame=frame,
                    model_spec=spec,
                    model_type="shared",
                    dna_lag_weeks=4,
                    dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
                    prior_config={},
                    direct_dna_outcome_ids=(
                        list(spec.segment_outcomes.values())
                        if model_name == "dna_kit"
                        else None
                    ),
                    causal_graph=None,
                    search_objects=(),
                )
                result = {
                    "status": "fit_not_started",
                    "validation_status": "not_run",
                    "model_name": model_name,
                    "engine": ENGINE_PYMC_RECTANGULAR,
                    "model_type": "shared_hierarchical_model_a",
                    "observations": int(frame["X_media"].shape[0]),
                    "markets": list(frame["markets"]),
                    "outcome_ids": list(frame["outcome_ids"]),
                    "channels": list(frame["channels"]),
                    "history_rows": int(np.asarray(frame["X_media_history"]).shape[0]),
                    "meta": _model_meta_payload(proposed.meta),
                }
        except Exception as exc:
            result = {
                "status": "fit_failed",
                "model_name": model_name,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            models.append(result)
            raise FitGateError(f"{model_name} fit failed: {exc}") from exc
        result["readiness_gate"] = model_gate[model_name]
        models.append(result)

    report = {
        "status": (
            "fit_completed_partial"
            if fit_enabled and only_model is not None
            else "fit_completed"
            if fit_enabled
            else "prepared_not_fitted"
        ),
        "validation_status": "pending_diagnostics_review" if fit_enabled else "not_run",
        "run_date": "2026-08-20",
        "engine": "PyMC",
        "source_pack": str(pack_dir),
        "source_evidence": list(pack.source_evidence),
        "target_window": {
            "start": GOVERNED_START,
            "end": GOVERNED_END,
            "frequency": TARGET_FREQUENCY,
            "weeks": int(len(pd.date_range(GOVERNED_START, GOVERNED_END, freq="7D"))),
            "maturity_cutoff": MATURITY_CUTOFF,
        },
        "source_readiness_gate": source_gate,
        "model_gate": model_gate,
        "approved_scope": {
            "family_history": {
                "structure": "joint/shared hierarchical Model A",
                "outcomes": [item.outcome_id for item in fh_outcomes],
            },
            "dna_kit": {
                "structure": "separate shared hierarchical model",
                "outcomes": [item.outcome_id for item in dna_outcomes],
            },
        },
        "retained_but_excluded": {
            "dna_performance_social": {
                "reason": "four impression observations unavailable; no fabrication, interpolation, backfill, or zero-fill",
                "initial_fit": "excluded from both product fits because the incomplete physical series is not safe for the DNA pathway input",
            },
            "branded_paid_search": {
                "inputs_retained": ["spend", "clicks"],
                "initial_fit": "excluded from official causal contribution calculation",
                "reason": "governed demand/cap/organic/direct decomposition is unavailable",
                "sensitivity_status": "retained for diagnostics; no causal coefficient certification",
            },
            "incomplete_physical_inputs": {
                "inputs": sorted(incomplete_inputs),
                "treatment": "excluded from initial fitted inputs; source series retained; no zero-fill or interpolation",
            },
            "no_target_window_variation": {
                "inputs": sorted(no_target_window_variation),
                "treatment": "excluded from initial fitted inputs because the requested estimation window has no estimable variation; source series and pre-window history retained",
            },
            "context": {
                "status": "retained native and diagnostic-only; no monthly-to-weekly fabrication or conversion",
            },
        },
        "nbt_completeness_records": nbt_metadata_by_outcome,
        "models": models,
        "selected_models": [config[0] for config in model_configs],
    }
    _write_json(output_dir / "production-fit-report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--draws", type=int, default=2000)
    parser.add_argument("--tune", type=int, default=1000)
    parser.add_argument("--chains", type=int, default=4)
    parser.add_argument("--target-accept", type=float, default=0.9)
    parser.add_argument("--seed", type=int, default=20260820)
    parser.add_argument(
        "--only-model",
        choices=("family_history", "dna_kit"),
        help="Run only one product model, preserving full-run seed assignment for resumable fits.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Run source/model-specific official preparation and build both models without sampling.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run(
            pack_dir=args.pack_dir,
            output_dir=args.output_dir,
            draws=args.draws,
            tune=args.tune,
            chains=args.chains,
            target_accept=args.target_accept,
            seed=args.seed,
            fit_enabled=not args.prepare_only,
            only_model=args.only_model,
        )
    except (FitGateError, OSError, ValueError) as exc:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(
            args.output_dir / "production-fit-failure.json",
            {
                "status": "fit_blocked",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "engine": "PyMC",
                "target_window": {
                    "start": GOVERNED_START,
                    "end": GOVERNED_END,
                    "frequency": TARGET_FREQUENCY,
                },
            },
        )
        print(f"UK production fit stopped: {type(exc).__name__}: {exc}")
        return 2
    print(f"UK production fit status: {report['status']}")
    print(f"Report: {args.output_dir / 'production-fit-report.json'}")
    for model in report["models"]:
        print(
            f"- {model['model_name']}: {model['status']} "
            f"({model.get('elapsed_seconds', 'n/a')}s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
