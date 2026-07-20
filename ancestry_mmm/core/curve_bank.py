"""
Curve bank: versioned storage for parametrised channel curves.

Every model run's shared curves (adstock decay, Hill K/S) and segment-level
parameters (response multipliers, DNA halo strength, promo sensitivity) are
written out as a plain JSON record rather than living only inside a trace
object - so a curve can be traced back to the model run, data window and
any geo-test/in-platform calibration event that produced or last updated
it, and so cross-market synthesis can consume curves without a full model
rebuild. Curves are appended, never overwritten in place, so history is a
straight append log with entry_id-based cross-references from calibration
records.

Every entry also carries the ModelApproval that authorised it (see
core.approval) - make_entry requires one, so an entry cannot be created
from an unapproved model run.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .approval import ModelApproval
from .hierarchical_model import FHModelMeta
from .predict import FHPosteriorParams


@dataclass
class CurveBankEntry:
    entry_id: str
    created_at: float
    run_label: str
    data_window: Tuple[str, str]
    markets: List[str]
    segments: List[str]
    channels: List[str]
    dna_channels: List[str]
    dna_segment: str
    decay_rate: Dict[str, float]
    hill_K: Dict[str, float]
    hill_S: Dict[str, float]
    beta: Dict[str, Dict[str, float]]
    halo_strength: Dict[str, float]
    promo_coef: Dict[str, float]
    approved_by: str
    approved_at: float
    approval_notes: str = ""
    approval_limitations: str = ""
    diagnostics_accepted: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CurveBankEntry":
        d = dict(d)
        d["data_window"] = tuple(d["data_window"])
        # Entries written before the approval gate was added have no
        # approved_by/approved_at - backfill an explicit "unknown" sentinel
        # rather than raising, so pre-existing curve bank history stays
        # loadable (and visibly flagged) instead of being silently dropped
        # by load_all_entries' broad except clause.
        d.setdefault("approved_by", "(unknown - pre-dates approval gate)")
        d.setdefault("approved_at", d.get("created_at", 0.0))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


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


def make_entry(
    meta: FHModelMeta,
    params: FHPosteriorParams,
    data_window: Tuple[str, str],
    run_label: str,
    approval: ModelApproval,
    notes: str = "",
) -> CurveBankEntry:
    """
    Build a curve bank entry from a fitted model's posterior parameters.

    `approval` is required, not optional: per the guide this build follows,
    "only an approved model should populate the official curve bank" - an
    unapproved model run has no way to reach `save_entry` through the normal
    call path (see pages/07_Results_Curve_Bank.py, which gates the "save to
    curve bank" action on an ModelApproval existing in session state).
    """
    if not isinstance(approval, ModelApproval):
        raise TypeError("make_entry requires a ModelApproval instance - see core.approval.")
    return CurveBankEntry(
        entry_id=str(uuid.uuid4()),
        created_at=time.time(),
        run_label=run_label,
        data_window=data_window,
        markets=meta.markets,
        segments=meta.segments,
        channels=meta.channels,
        dna_channels=meta.dna_channels,
        dna_segment=meta.dna_segment,
        decay_rate=params.decay_rate,
        hill_K=params.hill_K,
        hill_S=params.hill_S,
        beta=params.beta,
        halo_strength=params.halo_strength,
        promo_coef=params.promo_coef,
        approved_by=approval.approved_by,
        approved_at=approval.approved_at,
        approval_notes=approval.notes,
        approval_limitations=approval.known_limitations,
        diagnostics_accepted=list(approval.diagnostics_accepted),
        notes=notes,
    )


def save_entry(curve_bank_dir: Path, entry: CurveBankEntry) -> Path:
    curve_bank_dir = Path(curve_bank_dir)
    curve_bank_dir.mkdir(parents=True, exist_ok=True)
    path = curve_bank_dir / f"{int(entry.created_at)}_{entry.entry_id}.json"
    path.write_text(json.dumps(entry.to_dict(), indent=2))
    return path


def load_all_entries(curve_bank_dir: Path) -> List[CurveBankEntry]:
    curve_bank_dir = Path(curve_bank_dir)
    if not curve_bank_dir.exists():
        return []
    entries = []
    for path in sorted(curve_bank_dir.glob("*.json")):
        if path.name.startswith("calibration_"):
            continue
        try:
            entries.append(CurveBankEntry.from_dict(json.loads(path.read_text())))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return sorted(entries, key=lambda e: e.created_at)


def entries_to_dataframe(entries: List[CurveBankEntry]) -> pd.DataFrame:
    rows = []
    for e in entries:
        for seg in e.segments:
            for ch in e.channels:
                rows.append({
                    "entry_id": e.entry_id,
                    "run_label": e.run_label,
                    "created_at": pd.Timestamp.fromtimestamp(e.created_at),
                    "data_window_start": e.data_window[0],
                    "data_window_end": e.data_window[1],
                    "approved_by": e.approved_by,
                    "approved_at": pd.Timestamp.fromtimestamp(e.approved_at),
                    "segment": seg,
                    "channel": ch,
                    "decay_rate": e.decay_rate.get(ch),
                    "hill_K": e.hill_K.get(ch),
                    "hill_S": e.hill_S.get(ch),
                    "beta": e.beta.get(seg, {}).get(ch),
                    "halo_strength": e.halo_strength.get(seg) if ch in e.dna_channels else None,
                    "promo_coef": e.promo_coef.get(seg),
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
