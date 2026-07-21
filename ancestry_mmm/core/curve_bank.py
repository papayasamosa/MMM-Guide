"""
Curve bank: versioned storage for parametrised channel curves.

Phase 3a redesign (docs/curve_bank.md, docs/decision_log.md): one
`CurveBankEntry` per *curve* - (market, channel, segment-or-overall) - not
one per model run. This is what lets a market-specific fit (Model C) save
one record per market instead of collapsing every market into a single
run-level blob, and lets the curve bank UI filter/compare curves directly
rather than expanding a run into rows on the fly.

Every entry carries the ModelApproval that authorised the run it came from
(see core.approval) - `make_entries` requires one, and requires that it
match the exact model run being saved (model_run_id plus data/spec/
posterior fingerprints), so entries cannot be created from an unapproved
*or stale* model run. Entries are appended, never overwritten in place, so
history is a straight append log with entry_id-based cross-references from
calibration records.

Curve bank files written before this redesign (one JSON per model run, with
nested per-segment/per-channel dicts) remain loadable - `CurveBankEntry.
from_dict` detects the old shape and expands it into per-curve records
marked `legacy_format=True`, `curve_status="Legacy"`, `market=None` (the old
format predates market-specific curves entirely). Nothing on disk is
dropped or silently reinterpreted.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from .approval import ModelApproval, require_matching_approval
from .hierarchical_model import FHModelMeta
from .market_specific_predict import FHMarketSpecificPosteriorParams
from .predict import FHPosteriorParams

# docs/curve_bank.md's planned enum, plus "Shared" (this codebase's addition -
# see docs/decision_log.md): a Model A curve has no market-specific evidence
# to report, so labelling it "Locally estimated"/"Partially pooled"/
# "Transferred estimate" (all inherently about *market* evidence strength)
# would be actively misleading rather than merely imprecise.
CURVE_STATUS_SHARED = "Shared"
CURVE_STATUS_LOCALLY_ESTIMATED = "Locally estimated"
CURVE_STATUS_PARTIALLY_POOLED = "Partially pooled"
CURVE_STATUS_TRANSFERRED_ESTIMATE = "Transferred estimate"
CURVE_STATUS_LEGACY = "Legacy"

OVERALL = "Overall"


@dataclass
class CurveBankEntry:
    entry_id: str
    created_at: float
    run_label: str
    data_window: Tuple[str, str]

    model_type: str            # "shared" (Model A) | "market_specific" (Model C)
    market: Optional[str]      # None for a shared curve; a market name for Model C
    channel: str
    segment_or_overall: str    # one of the model's segments, or OVERALL
    dna_channel: bool
    curve_status: str          # one of the CURVE_STATUS_* constants above

    decay_rate: float
    hill_K: float
    hill_S: float
    beta: float
    halo_strength: Optional[float]

    # "spend" (always) or "media_unit" (Phase 3b, only where a media-unit
    # mapping exists - see make_media_unit_entries). currency/unit_type/
    # cost_per_unit are None for a "spend" entry.
    input_type: str = "spend"
    currency: Optional[str] = None
    unit_type: Optional[str] = None
    # Average historical cost-per-unit (core.media_units.historical_cost_trend)
    # this entry's media-unit axis was derived from - only set on
    # input_type="media_unit" entries; None for "spend" entries.
    cost_per_unit: Optional[float] = None

    approved_by: str = ""
    approved_at: float = 0.0
    approval_notes: str = ""
    approval_limitations: str = ""
    diagnostics_accepted: List[str] = field(default_factory=list)
    model_run_id: str = ""
    data_fingerprint: str = ""
    model_spec_fingerprint: str = ""
    posterior_fingerprint: str = ""
    legacy_approval: bool = False
    # True only for entries synthesised from a pre-Phase-3a, one-JSON-per-run
    # file at load time - see module docstring.
    legacy_format: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> List["CurveBankEntry"]:
        """Returns a list, not a single entry: a legacy (pre-Phase-3a)
        run-level record expands into several per-curve entries; a
        current-format record returns a single-item list, so callers always
        iterate the same way regardless of which shape was on disk."""
        if "segment_or_overall" not in d:
            return _expand_legacy_entry(d)
        d = dict(d)
        d["data_window"] = tuple(d["data_window"])
        known = {f for f in cls.__dataclass_fields__}
        return [cls(**{k: v for k, v in d.items() if k in known})]


def _expand_legacy_entry(d: dict) -> List["CurveBankEntry"]:
    """A pre-Phase-3a entry stored one JSON object per model run, with
    `beta`/`hill_K`/etc. keyed by segment/channel. Expand it into the
    current per-curve shape: one entry per (segment, channel), plus one
    "Overall" entry per channel (beta summed across segments - valid because
    response = beta * saturation is linear in beta, so summing betas before
    multiplying by the shared saturation curve equals summing responses)."""
    segments: List[str] = d.get("segments", [])
    channels: List[str] = d.get("channels", [])
    dna_channels = set(d.get("dna_channels", []))
    decay_rate = d.get("decay_rate", {})
    hill_K = d.get("hill_K", {})
    hill_S = d.get("hill_S", {})
    beta = d.get("beta", {})
    halo_strength = d.get("halo_strength", {})

    shared_fields = {
        "created_at": d.get("created_at", 0.0),
        "run_label": d.get("run_label", ""),
        "data_window": tuple(d.get("data_window", ("", ""))),
        "model_type": "shared",  # the pre-Phase-3a era predates Model C entirely
        "market": None,
        "approved_by": d.get("approved_by", "(unknown - pre-dates approval gate)"),
        "approved_at": d.get("approved_at", d.get("created_at", 0.0)),
        "approval_notes": d.get("approval_notes", ""),
        "approval_limitations": d.get("approval_limitations", ""),
        "diagnostics_accepted": list(d.get("diagnostics_accepted", [])),
        "model_run_id": d.get("model_run_id", ""),
        "data_fingerprint": d.get("data_fingerprint", ""),
        "model_spec_fingerprint": d.get("model_spec_fingerprint", ""),
        "posterior_fingerprint": d.get("posterior_fingerprint", ""),
        "legacy_approval": d.get("legacy_approval", "model_run_id" not in d),
        "legacy_format": True,
        "notes": d.get("notes", ""),
    }
    base_entry_id = d.get("entry_id", str(uuid.uuid4()))

    entries: List[CurveBankEntry] = []
    for channel in channels:
        is_dna = channel in dna_channels
        overall_beta = 0.0
        for segment in segments:
            b = beta.get(segment, {}).get(channel, 0.0)
            overall_beta += b
            entries.append(CurveBankEntry(
                entry_id=f"{base_entry_id}::{segment}::{channel}",
                channel=channel, segment_or_overall=segment, dna_channel=is_dna,
                curve_status=CURVE_STATUS_LEGACY,
                decay_rate=decay_rate.get(channel, 0.0), hill_K=hill_K.get(channel, 0.0),
                hill_S=hill_S.get(channel, 0.0), beta=b,
                halo_strength=halo_strength.get(segment) if is_dna else None,
                **shared_fields,
            ))
        entries.append(CurveBankEntry(
            entry_id=f"{base_entry_id}::{OVERALL}::{channel}",
            channel=channel, segment_or_overall=OVERALL, dna_channel=is_dna,
            curve_status=CURVE_STATUS_LEGACY,
            decay_rate=decay_rate.get(channel, 0.0), hill_K=hill_K.get(channel, 0.0),
            hill_S=hill_S.get(channel, 0.0), beta=overall_beta, halo_strength=None,
            **shared_fields,
        ))
    return entries


@dataclass
class CalibrationRecord:
    record_id: str
    entry_id: str
    created_at: float
    channel: str
    segment: str
    test_type: str  # "geo" | "in_platform"
    model_estimate: float
    test_estimate: float
    test_ci_low: Optional[float]
    test_ci_high: Optional[float]
    agreement: str  # "agrees" | "diverges"
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationRecord":
        return cls(**d)


def make_entries(
    meta: FHModelMeta,
    params: Union[FHPosteriorParams, FHMarketSpecificPosteriorParams],
    data_window: Tuple[str, str],
    run_label: str,
    approval: ModelApproval,
    *,
    model_type: str,
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
    evidence_tiers: Optional[Dict[str, Dict[str, str]]] = None,
    currency_by_market: Optional[Dict[str, str]] = None,
    notes: str = "",
) -> List[CurveBankEntry]:
    """
    Build this run's full set of curve bank entries: one per (channel,
    segment-or-overall), and for a market-specific fit, one per market on
    top of that.

    `model_type` is `"shared"` (Model A - `params` is `FHPosteriorParams`,
    one curve per channel) or `"market_specific"` (Model C - `params` is
    `FHMarketSpecificPosteriorParams`, one curve per market per channel).
    For `"market_specific"`, `evidence_tiers` (typically
    `core.evidence_tiers.classify_all_markets(trace, frame, meta)`, computed
    by the caller since building it here would require the trace, not just
    `params`) is required - every market/channel entry needs a curve status.

    `approval` must match the exact model run being saved - `model_run_id`
    and the three fingerprints are the current model's identity (see
    core.fingerprint), computed by the caller from the same artefacts that
    produced `meta`/`params`. Enforced here (not only in the Streamlit page)
    so a direct call to `make_entries` can't bypass it - raises
    ApprovalMismatchError for missing, legacy, or mismatched approval.
    """
    if model_type not in ("shared", "market_specific"):
        raise ValueError(f"model_type must be 'shared' or 'market_specific', got {model_type!r}")
    if model_type == "market_specific" and evidence_tiers is None:
        raise ValueError("evidence_tiers is required when model_type='market_specific'")

    require_matching_approval(
        approval,
        model_run_id=model_run_id,
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
    )

    shared_fields: Dict[str, Any] = {
        "created_at": time.time(),
        "run_label": run_label,
        "data_window": data_window,
        "model_type": model_type,
        "approved_by": approval.approved_by,
        "approved_at": approval.approved_at,
        "approval_notes": approval.notes,
        "approval_limitations": approval.known_limitations,
        "diagnostics_accepted": list(approval.diagnostics_accepted),
        "model_run_id": model_run_id,
        "data_fingerprint": data_fingerprint,
        "model_spec_fingerprint": model_spec_fingerprint,
        "posterior_fingerprint": posterior_fingerprint,
        "legacy_approval": False,
        "legacy_format": False,
        "notes": notes,
    }

    entries: List[CurveBankEntry] = []
    markets: List[Optional[str]] = meta.markets if model_type == "market_specific" else [None]
    currency_by_market = currency_by_market or {}

    for market in markets:
        for channel in meta.channels:
            is_dna = channel in meta.dna_channels
            if model_type == "market_specific":
                decay_rate = params.decay_rate[channel]
                hill_K = params.hill_K[market][channel]
                hill_S = params.hill_S[channel]
                beta_by_segment = {s: params.beta[market][s][channel] for s in meta.segments}
                curve_status = evidence_tiers[market][channel]
                currency = currency_by_market.get(market)
            else:
                decay_rate = params.decay_rate[channel]
                hill_K = params.hill_K[channel]
                hill_S = params.hill_S[channel]
                beta_by_segment = {s: params.beta[s][channel] for s in meta.segments}
                curve_status = CURVE_STATUS_SHARED
                currency = None

            for segment, beta_val in beta_by_segment.items():
                entries.append(CurveBankEntry(
                    entry_id=str(uuid.uuid4()), market=market, channel=channel,
                    segment_or_overall=segment, dna_channel=is_dna, curve_status=curve_status,
                    decay_rate=decay_rate, hill_K=hill_K, hill_S=hill_S, beta=beta_val,
                    halo_strength=params.halo_strength.get(segment) if is_dna else None,
                    currency=currency, **shared_fields,
                ))
            entries.append(CurveBankEntry(
                entry_id=str(uuid.uuid4()), market=market, channel=channel,
                segment_or_overall=OVERALL, dna_channel=is_dna, curve_status=curve_status,
                decay_rate=decay_rate, hill_K=hill_K, hill_S=hill_S,
                beta=sum(beta_by_segment.values()), halo_strength=None,
                currency=currency, **shared_fields,
            ))

    return entries


def make_media_unit_entries(
    entries: List[CurveBankEntry],
    media_unit_info: Dict[Tuple[Optional[str], str], Dict[str, Any]],
) -> List[CurveBankEntry]:
    """
    For each `input_type="spend"` entry in `entries` whose (market, channel)
    has an entry in `media_unit_info` - `{"unit_type": ..., "currency": ...,
    "avg_cost_per_unit": ...}`, typically built from
    `core.market_config.ChannelMediaUnitConfig` and
    `core.media_units.historical_cost_trend` - produce a mirrored
    `input_type="media_unit"` entry carrying the same curve parameters
    (`beta`/`hill_K`/`hill_S`/`decay_rate` don't change; only the x-axis
    interpretation does, applied at curve-generation time via
    `core.media_units.response_unit_curve`, not stored twice here) plus the
    media-unit context needed to reconstruct that curve later.

    Entries with no mapping in `media_unit_info` are skipped, not defaulted -
    a media-unit curve without an actual cost-per-unit relationship to back
    it would be fabricated, not derived.
    """
    mirrored: List[CurveBankEntry] = []
    for e in entries:
        if e.input_type != "spend":
            continue
        info = media_unit_info.get((e.market, e.channel))
        if info is None:
            continue
        mirrored.append(replace(
            e, entry_id=str(uuid.uuid4()), input_type="media_unit",
            unit_type=info.get("unit_type"),
            currency=info.get("currency") or e.currency,
            cost_per_unit=info.get("avg_cost_per_unit"),
        ))
    return mirrored


def save_entries(curve_bank_dir: Path, entries: List[CurveBankEntry]) -> List[Path]:
    """One JSON file per entry (per curve), all sharing the same
    `model_run_id` so a single save's entries can be found together."""
    curve_bank_dir = Path(curve_bank_dir)
    curve_bank_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for entry in entries:
        path = curve_bank_dir / f"{int(entry.created_at)}_{entry.entry_id}.json"
        path.write_text(json.dumps(entry.to_dict(), indent=2))
        paths.append(path)
    return paths


def load_all_entries(curve_bank_dir: Path) -> List[CurveBankEntry]:
    curve_bank_dir = Path(curve_bank_dir)
    if not curve_bank_dir.exists():
        return []
    entries: List[CurveBankEntry] = []
    for path in sorted(curve_bank_dir.glob("*.json")):
        if path.name.startswith("calibration_"):
            continue
        try:
            entries.extend(CurveBankEntry.from_dict(json.loads(path.read_text())))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return sorted(entries, key=lambda e: (e.created_at, e.entry_id))


def entries_to_dataframe(entries: List[CurveBankEntry]) -> pd.DataFrame:
    """One row per curve (already the entry's own granularity) - filter by
    market/channel/segment/curve_status/model_run_id/currency/unit_type
    directly on the returned frame, per docs/curve_bank.md's planned UI."""
    rows = []
    for e in entries:
        rows.append({
            "entry_id": e.entry_id,
            "run_label": e.run_label,
            "created_at": pd.Timestamp.fromtimestamp(e.created_at),
            "data_window_start": e.data_window[0],
            "data_window_end": e.data_window[1],
            "model_type": e.model_type,
            "market": e.market or "(shared)",
            "channel": e.channel,
            "segment_or_overall": e.segment_or_overall,
            "curve_status": e.curve_status,
            "input_type": e.input_type,
            "currency": e.currency,
            "unit_type": e.unit_type,
            "cost_per_unit": e.cost_per_unit,
            "decay_rate": e.decay_rate,
            "hill_K": e.hill_K,
            "hill_S": e.hill_S,
            "beta": e.beta,
            "halo_strength": e.halo_strength,
            "approved_by": e.approved_by,
            "approved_at": pd.Timestamp.fromtimestamp(e.approved_at) if e.approved_at else None,
            "model_run_id": e.model_run_id,
            "legacy_approval": e.legacy_approval,
            "legacy_format": e.legacy_format,
        })
    return pd.DataFrame(rows)


def compare_to_test(
    model_estimate: float,
    test_estimate: float,
    test_ci: Optional[Tuple[float, float]] = None,
    tolerance_pct: float = 25.0,
) -> str:
    """
    "agrees" if the model estimate falls inside the test's CI (if given) or
    within `tolerance_pct` of the test point estimate; "diverges" otherwise.
    """
    if test_ci is not None:
        lo, hi = test_ci
        if lo <= model_estimate <= hi:
            return "agrees"
    if test_estimate == 0:
        return "agrees" if model_estimate == 0 else "diverges"
    pct_diff = abs(model_estimate - test_estimate) / abs(test_estimate) * 100
    return "agrees" if pct_diff <= tolerance_pct else "diverges"


def record_calibration(
    curve_bank_dir: Path,
    entry_id: str,
    channel: str,
    segment: str,
    test_type: str,
    model_estimate: float,
    test_estimate: float,
    test_ci: Optional[Tuple[float, float]] = None,
    tolerance_pct: float = 25.0,
    notes: str = "",
) -> CalibrationRecord:
    """
    Log a geo-test/in-platform-test result against a curve bank entry so the
    curve's calibration history is inspectable. This does NOT automatically
    refit the curve (that's an analyst decision) - it records agreement so a
    future refit or manual adjustment has an audit trail.
    """
    record = CalibrationRecord(
        record_id=str(uuid.uuid4()),
        entry_id=entry_id,
        created_at=time.time(),
        channel=channel,
        segment=segment,
        test_type=test_type,
        model_estimate=model_estimate,
        test_estimate=test_estimate,
        test_ci_low=test_ci[0] if test_ci else None,
        test_ci_high=test_ci[1] if test_ci else None,
        agreement=compare_to_test(model_estimate, test_estimate, test_ci, tolerance_pct),
        notes=notes,
    )
    curve_bank_dir = Path(curve_bank_dir)
    curve_bank_dir.mkdir(parents=True, exist_ok=True)
    path = curve_bank_dir / f"calibration_{int(record.created_at)}_{record.record_id}.json"
    path.write_text(json.dumps(record.to_dict(), indent=2))
    return record


def load_all_calibrations(curve_bank_dir: Path) -> List[CalibrationRecord]:
    curve_bank_dir = Path(curve_bank_dir)
    if not curve_bank_dir.exists():
        return []
    records = []
    for path in sorted(curve_bank_dir.glob("calibration_*.json")):
        try:
            records.append(CalibrationRecord.from_dict(json.loads(path.read_text())))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return sorted(records, key=lambda r: r.created_at)


def calibrations_to_dataframe(records: List[CalibrationRecord]) -> pd.DataFrame:
    return pd.DataFrame([r.to_dict() for r in records])
