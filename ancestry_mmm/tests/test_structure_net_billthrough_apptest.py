"""The structure page must communicate supplied, not reconstructed, NBT."""
from pathlib import Path

def test_structure_page_uses_authoritative_uploaded_nbt():
    source = Path('ancestry_mmm/pages/03_Structure_Segments_Markets.py').read_text()
    assert 'authoritative weekly count' in source
    assert 'NetBillthroughOfferRule' not in source
