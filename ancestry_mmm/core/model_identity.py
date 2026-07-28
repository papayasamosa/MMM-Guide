"""
Canonical model identity for validation binding.

PR 53B: Immutable proof of which exact fitted model, data, specification,
and posterior a validation result was evaluated against. Never inferred
from ``FHModelMeta`` — always supplied explicitly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelIdentity:
    """Immutable proof of a specific model run's identity.

    All fields are required and must be non-blank. An identity with any
    blank field is considered incomplete and cannot be used for official
    validation.

    Parameters
    ----------
    model_run_id : str
        UUID minted on every model fit — see pages/05_Model_Training.py.
    data_fingerprint : str
        SHA-256 fingerprint of the modelling data at fit time.
    model_spec_fingerprint : str
        SHA-256 fingerprint of the model specification (structure + priors).
    posterior_fingerprint : str
        SHA-256 fingerprint of the fitted posterior.
    """
    model_run_id: str
    data_fingerprint: str
    model_spec_fingerprint: str
    posterior_fingerprint: str

    def __post_init__(self) -> None:
        if not self.model_run_id or not self.model_run_id.strip():
            raise ValueError("ModelIdentity.model_run_id must be non-blank")
        if not self.data_fingerprint or not self.data_fingerprint.strip():
            raise ValueError("ModelIdentity.data_fingerprint must be non-blank")
        if not self.model_spec_fingerprint or not self.model_spec_fingerprint.strip():
            raise ValueError("ModelIdentity.model_spec_fingerprint must be non-blank")
        if not self.posterior_fingerprint or not self.posterior_fingerprint.strip():
            raise ValueError("ModelIdentity.posterior_fingerprint must be non-blank")

    def is_complete(self) -> bool:
        """True if every field is non-blank."""
        return all([
            self.model_run_id and self.model_run_id.strip(),
            self.data_fingerprint and self.data_fingerprint.strip(),
            self.model_spec_fingerprint and self.model_spec_fingerprint.strip(),
            self.posterior_fingerprint and self.posterior_fingerprint.strip(),
        ])

    def fingerprint(self) -> str:
        """Deterministic SHA-256 fingerprint of this identity."""
        payload = {
            "model_run_id": self.model_run_id,
            "data_fingerprint": self.data_fingerprint,
            "model_spec_fingerprint": self.model_spec_fingerprint,
            "posterior_fingerprint": self.posterior_fingerprint,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def matches(self, other: ModelIdentity) -> bool:
        """True if every field matches exactly.

        Both identities must be complete. An incomplete identity never
        matches, even if the non-blank fields happen to agree."""
        if not self.is_complete() or not other.is_complete():
            return False
        return (
            self.model_run_id == other.model_run_id
            and self.data_fingerprint == other.data_fingerprint
            and self.model_spec_fingerprint == other.model_spec_fingerprint
            and self.posterior_fingerprint == other.posterior_fingerprint
        )

    def to_dict(self) -> dict:
        return {
            "model_run_id": self.model_run_id,
            "data_fingerprint": self.data_fingerprint,
            "model_spec_fingerprint": self.model_spec_fingerprint,
            "posterior_fingerprint": self.posterior_fingerprint,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ModelIdentity:
        known = {"model_run_id", "data_fingerprint", "model_spec_fingerprint", "posterior_fingerprint"}
        payload = {k: v for k, v in d.items() if k in known}
        return cls(**payload)
