"""Make the repo root importable as `ancestry_mmm.*` regardless of pytest's invocation directory."""

import sys
from pathlib import Path
from typing import Dict

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def pathway_strength_from_flat(flat: Dict[str, float], channel: str) -> Dict[str, Dict[str, float]]:
    """Test helper (PR G1): convert the pre-PR-G1 `halo_strength` shape
    (`Dict[outcome_id, float]`, implicitly applied to whichever channel was
    *the* DNA channel) into the current `Dict[outcome_id, Dict[channel,
    float]]` `pathway_strength` shape used by `FHPosteriorParams`/
    `FHMarketSpecificPosteriorParams` - for fixtures with a single DNA
    channel, which is every existing fixture predating this generalisation."""
    return {oid: {channel: val} for oid, val in flat.items()}
