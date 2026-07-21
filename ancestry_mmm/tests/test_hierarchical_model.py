"""Tests for the pure-Python helpers in core.hierarchical_model - the
direct_dna_segments generalisation (docs/dna_fh_causal_structure.md).

Matches the project's existing convention (see test_market_specific_model.py)
of not building/compiling an actual PyMC model in the test suite, since
that's slow and already covered by manual/offline verification
(docs/decision_log.md). What's covered here is everything that doesn't
require a PyMC model: FHModelMeta's own default behaviour and the
_resolve_direct_dna_segments helper both builders call before touching PyMC
at all.
"""

import pytest

from ancestry_mmm.core.hierarchical_model import FHModelMeta, _resolve_direct_dna_segments


def _meta(**overrides) -> FHModelMeta:
    defaults = dict(
        markets=["UK"], segments=["New", "DNA_CrossSell", "Winback"], channels=["TV", "DNA_Media"],
        dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
        dna_segment="DNA_CrossSell", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
    )
    defaults.update(overrides)
    return FHModelMeta(**defaults)


class TestFHModelMetaDirectDnaSegmentsDefault:
    def test_defaults_to_just_the_dna_segment_when_omitted(self):
        meta = _meta()
        assert meta.direct_dna_segments == ["DNA_CrossSell"]

    def test_explicit_value_is_preserved(self):
        meta = _meta(direct_dna_segments=["DNA_CrossSell", "New Customer"])
        assert meta.direct_dna_segments == ["DNA_CrossSell", "New Customer"]

    def test_empty_list_falls_back_to_dna_segment_too(self):
        # A dataclass constructed with an explicit empty list (e.g. from a
        # legacy bundle's JSON round trip, where the field was absent and
        # default_factory=list kicked in) must behave identically to
        # omitting the argument entirely.
        meta = _meta(direct_dna_segments=[])
        assert meta.direct_dna_segments == ["DNA_CrossSell"]


class TestResolveDirectDnaSegments:
    SEGMENTS = ["New", "DNA_CrossSell", "Winback", "New Customer", "Existing FH Customer"]

    def test_none_defaults_to_just_dna_segment(self):
        assert _resolve_direct_dna_segments(self.SEGMENTS, "DNA_CrossSell", None) == ["DNA_CrossSell"]

    def test_dna_segment_is_always_included_even_if_omitted_from_the_explicit_list(self):
        resolved = _resolve_direct_dna_segments(self.SEGMENTS, "DNA_CrossSell", ["New Customer"])
        assert set(resolved) == {"DNA_CrossSell", "New Customer"}

    def test_explicit_list_already_containing_dna_segment_is_not_duplicated(self):
        resolved = _resolve_direct_dna_segments(
            self.SEGMENTS, "DNA_CrossSell", ["DNA_CrossSell", "New Customer", "Existing FH Customer"],
        )
        assert resolved.count("DNA_CrossSell") == 1
        assert set(resolved) == {"DNA_CrossSell", "New Customer", "Existing FH Customer"}

    def test_unknown_segment_raises(self):
        with pytest.raises(ValueError, match="unknown segment"):
            _resolve_direct_dna_segments(self.SEGMENTS, "DNA_CrossSell", ["Not A Real Segment"])
