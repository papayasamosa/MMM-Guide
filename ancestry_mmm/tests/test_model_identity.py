"""
Tests for ``core.model_identity.ModelIdentity`` — PR 53B.
"""

from __future__ import annotations

import pytest
from ancestry_mmm.core.model_identity import ModelIdentity


class TestModelIdentityCreation:
    def test_valid_identity_created(self):
        identity = ModelIdentity(
            model_run_id="run-123",
            data_fingerprint="data-abc",
            model_spec_fingerprint="spec-def",
            posterior_fingerprint="post-ghi",
        )
        assert identity.model_run_id == "run-123"
        assert identity.is_complete()

    def test_blank_run_id_raises(self):
        with pytest.raises(ValueError, match="model_run_id must be non-blank"):
            ModelIdentity(
                model_run_id="", data_fingerprint="data",
                model_spec_fingerprint="spec", posterior_fingerprint="post",
            )

    def test_blank_data_fingerprint_raises(self):
        with pytest.raises(ValueError, match="data_fingerprint must be non-blank"):
            ModelIdentity(
                model_run_id="run", data_fingerprint="",
                model_spec_fingerprint="spec", posterior_fingerprint="post",
            )

    def test_blank_spec_fingerprint_raises(self):
        with pytest.raises(ValueError, match="model_spec_fingerprint must be non-blank"):
            ModelIdentity(
                model_run_id="run", data_fingerprint="data",
                model_spec_fingerprint="", posterior_fingerprint="post",
            )

    def test_blank_posterior_fingerprint_raises(self):
        with pytest.raises(ValueError, match="posterior_fingerprint must be non-blank"):
            ModelIdentity(
                model_run_id="run", data_fingerprint="data",
                model_spec_fingerprint="spec", posterior_fingerprint="",
            )


class TestModelIdentityProperties:
    def test_is_complete_true_when_all_populated(self):
        identity = ModelIdentity(
            model_run_id="r", data_fingerprint="d",
            model_spec_fingerprint="s", posterior_fingerprint="p",
        )
        assert identity.is_complete()

    def test_is_complete_false_when_any_missing(self):
        identity = ModelIdentity(
            model_run_id="r", data_fingerprint="d",
            model_spec_fingerprint="s", posterior_fingerprint="",
        )
        assert not identity.is_complete()


class TestModelIdentityMatching:
    def test_identical_identities_match(self):
        a = ModelIdentity("r", "d", "s", "p")
        b = ModelIdentity("r", "d", "s", "p")
        assert a.matches(b)
        assert b.matches(a)

    def test_different_run_id_does_not_match(self):
        a = ModelIdentity("r1", "d", "s", "p")
        b = ModelIdentity("r2", "d", "s", "p")
        assert not a.matches(b)

    def test_different_data_does_not_match(self):
        a = ModelIdentity("r", "d1", "s", "p")
        b = ModelIdentity("r", "d2", "s", "p")
        assert not a.matches(b)

    def test_incomplete_never_matches(self):
        complete = ModelIdentity("r", "d", "s", "p")
        incomplete = ModelIdentity("r", "d", "s", "")
        assert not complete.matches(incomplete)
        assert not incomplete.matches(complete)


class TestModelIdentityFingerprint:
    def test_fingerprint_is_deterministic(self):
        a = ModelIdentity("r", "d", "s", "p")
        b = ModelIdentity("r", "d", "s", "p")
        assert a.fingerprint() == b.fingerprint()

    def test_fingerprint_changes_on_any_field(self):
        a = ModelIdentity("r", "d", "s", "p")
        b = ModelIdentity("r2", "d", "s", "p")
        assert a.fingerprint() != b.fingerprint()


class TestModelIdentityRoundTrip:
    def test_to_dict_from_dict(self):
        original = ModelIdentity("r", "d", "s", "p")
        d = original.to_dict()
        restored = ModelIdentity.from_dict(d)
        assert original == restored
        assert original.matches(restored)

    def test_from_dict_ignores_unknown_keys(self):
        d = {"model_run_id": "r", "data_fingerprint": "d",
             "model_spec_fingerprint": "s", "posterior_fingerprint": "p",
             "extra_field": "should be ignored"}
        identity = ModelIdentity.from_dict(d)
        assert identity.model_run_id == "r"
