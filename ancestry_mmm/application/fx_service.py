"""Application boundary for Finance-supplied FX rate-set uploads.

This service deliberately accepts values supplied by the analyst/Finance and
never supplies a live rate, a spot-rate fallback, or a guessed constant. It
turns the existing network-free provider contract into a validated,
versioned, JSON-safe project object.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, List, Mapping, Sequence, Tuple
from uuid import uuid4

import pandas as pd

from ancestry_mmm.core.fx_conversion import assert_valid_conversion_method
from ancestry_mmm.core.fx_provider import (
    ManualUploadFXProvider,
    ManualUploadRateRow,
    validate_rate_records,
)
from ancestry_mmm.core.fx_rates import (
    FXRateRecord,
    FXRateSet,
    compute_records_fingerprint,
)


class FXUploadValidationError(ValueError):
    """Raised when an FX upload cannot become a governed rate set."""


def _read_upload(source: Any) -> pd.DataFrame:
    if isinstance(source, pd.DataFrame):
        return source.copy()
    if isinstance(source, (bytes, bytearray)):
        return pd.read_csv(BytesIO(bytes(source)))
    if isinstance(source, str):
        return pd.read_csv(StringIO(source))
    if isinstance(source, Path):
        return pd.read_csv(source)
    if hasattr(source, "read"):
        return pd.read_csv(source)
    raise FXUploadValidationError(
        "FX upload must be a DataFrame, CSV path, text, bytes, or readable file."
    )


def build_manual_fx_rate_set(
    source: Any,
    *,
    rate_set_id: str,
    rate_set_version: int,
    name: str,
    provider: str,
    base_or_reference_currency: str,
    start_date: str,
    end_date: str,
    rate_policy: str,
    retrieved_at: str | None = None,
    approval_status: str = "pending",
    approved_by: str | None = None,
    approved_at: str | None = None,
) -> Tuple[FXRateSet, List[FXRateRecord]]:
    """Validate a Finance/manual CSV and build its immutable rate set.

    Required columns are ``rate_date``, ``source_currency``,
    ``target_currency``, ``rate``, ``method`` and ``frequency``. Annual rows
    additionally require ``financial_year``. The service rejects malformed
    rows, duplicate pair/date observations, impossible sanity-check values,
    missing metadata, and unapproved conversion methods.
    """

    if not rate_set_id or not name or not provider or not rate_policy:
        raise FXUploadValidationError(
            "rate_set_id, name, provider, and rate_policy are required."
        )
    if not start_date or not end_date or end_date < start_date:
        raise FXUploadValidationError("FX rate-set date range is invalid.")
    frame = _read_upload(source)
    required = {
        "rate_date",
        "source_currency",
        "target_currency",
        "rate",
        "method",
        "frequency",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise FXUploadValidationError(
            "FX upload is missing required column(s): " + ", ".join(missing)
        )
    if frame.empty:
        raise FXUploadValidationError("FX upload contains no rate rows.")

    rows: List[ManualUploadRateRow] = []
    for index, values in frame.iterrows():
        try:
            method = str(values["method"])
            assert_valid_conversion_method(method)
            frequency = str(values["frequency"])
            rate = Decimal(str(values["rate"]))
            if not rate.is_finite():
                raise FXUploadValidationError("rate must be finite")
            rows.append(
                ManualUploadRateRow(
                    rate_date=str(values["rate_date"]),
                    source_currency=str(values["source_currency"]).upper(),
                    target_currency=str(values["target_currency"]).upper(),
                    rate=rate,
                    method=method,
                    frequency=frequency,
                    financial_year=(
                        None
                        if pd.isna(values.get("financial_year"))
                        else str(values.get("financial_year"))
                    ),
                )
            )
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise FXUploadValidationError(
                f"FX upload row {index + 1} is invalid: {exc}"
            ) from exc

    provider_adapter = ManualUploadFXProvider(rows, provider_name=provider)
    pairs = [(row.source_currency, row.target_currency) for row in rows]
    records = provider_adapter.fetch_rates(pairs, start_date, end_date)
    if len(records) != len(rows):
        raise FXUploadValidationError(
            "FX upload contains a row outside the declared rate-set date range."
        )
    issues = validate_rate_records(records)
    if issues:
        raise FXUploadValidationError(
            "FX upload validation failed: "
            + "; ".join(issue.detail for issue in issues)
        )
    records_fingerprint = compute_records_fingerprint(records)
    rate_set = FXRateSet(
        rate_set_id=rate_set_id,
        rate_set_version=rate_set_version,
        name=name,
        provider=provider,
        base_or_reference_currency=base_or_reference_currency.upper(),
        start_date=start_date,
        end_date=end_date,
        retrieved_at=retrieved_at or datetime.now(timezone.utc).isoformat(),
        rate_policy=rate_policy,
        records_fingerprint=records_fingerprint,
        approval_status=approval_status,
        approved_by=approved_by,
        approved_at=approved_at,
    )
    return rate_set, records


def validate_persisted_fx_rate_set(
    rate_set_payload: Mapping[str, Any], records_payload: Sequence[Mapping[str, Any]]
) -> Tuple[FXRateSet, List[FXRateRecord]]:
    """Revalidate a bundle's rate set and records before session use."""

    rate_set = FXRateSet.from_dict(rate_set_payload)
    records = [FXRateRecord.from_dict(value) for value in records_payload]
    if compute_records_fingerprint(records) != rate_set.records_fingerprint:
        raise FXUploadValidationError(
            "Persisted FX records do not match the rate-set records_fingerprint."
        )
    issues = validate_rate_records(records)
    if issues:
        raise FXUploadValidationError(
            "Persisted FX records failed validation: "
            + "; ".join(issue.detail for issue in issues)
        )
    return rate_set, records


def resolve_approved_fx_rate(
    rate_set: FXRateSet,
    records: Sequence[FXRateRecord],
    *,
    source_currency: str,
    target_currency: str,
    as_of_date: str,
) -> Decimal | None:
    """Resolve a governed historical rate for an official monetary curve.

    Only an explicitly approved, fingerprint-consistent rate set can supply
    this value.  The latest observation on or before ``as_of_date`` is used;
    missing coverage returns ``None`` so the caller can block rather than
    inventing a spot rate or silently falling back to ``1``.  Same-currency
    identity conversion is handled by the caller because it is not an FX
    record.
    """

    if rate_set.approval_status != "approved":
        return None
    if compute_records_fingerprint(records) != rate_set.records_fingerprint:
        raise FXUploadValidationError(
            "FX records do not match the approved rate-set records_fingerprint."
        )
    source = source_currency.upper()
    target = target_currency.upper()
    candidates = [
        record
        for record in records
        if record.source_currency == source
        and record.target_currency == target
        and record.rate_date <= as_of_date
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda record: (record.rate_date, record.rate_id)).rate


def new_manual_rate_set_id() -> str:
    """Return a session-safe lineage id; values still require Finance review."""

    return f"manual-fx-{uuid4().hex}"


__all__ = [
    "FXUploadValidationError",
    "build_manual_fx_rate_set",
    "new_manual_rate_set_id",
    "resolve_approved_fx_rate",
    "validate_persisted_fx_rate_set",
]
