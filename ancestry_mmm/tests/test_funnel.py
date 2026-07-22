"""Tests for core.funnel - funnel-coherence diagnostics (PR E.2 requirement
#7). Diagnostics/warnings only - see module docstring for why this is
deliberately not a constrained funnel model."""

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.funnel import (
    FunnelLink,
    funnel_channel_attribution_consistency,
    funnel_coherence_diagnostics,
    funnel_links_fingerprint_payload,
    validate_funnel_links,
)


class TestFunnelLinkRoundTrip:
    def test_to_dict_from_dict_round_trips(self):
        link = FunnelLink(upstream_outcome_id="fh_new_signup", downstream_outcome_id="fh_new_gsa")
        restored = FunnelLink.from_dict(link.to_dict())
        assert restored == link


class TestValidateFunnelLinks:
    def test_valid_link_has_no_errors(self):
        links = [FunnelLink("fh_new_signup", "fh_new_gsa")]
        assert validate_funnel_links(links, ["fh_new_signup", "fh_new_gsa"]) == []

    def test_unknown_upstream_outcome_id_is_an_error(self):
        links = [FunnelLink("does_not_exist", "fh_new_gsa")]
        errors = validate_funnel_links(links, ["fh_new_gsa"])
        assert any("unknown upstream" in e.lower() for e in errors)

    def test_unknown_downstream_outcome_id_is_an_error(self):
        links = [FunnelLink("fh_new_signup", "does_not_exist")]
        errors = validate_funnel_links(links, ["fh_new_signup"])
        assert any("unknown downstream" in e.lower() for e in errors)

    def test_self_link_is_an_error(self):
        links = [FunnelLink("fh_new_gsa", "fh_new_gsa")]
        errors = validate_funnel_links(links, ["fh_new_gsa"])
        assert any("same outcome_id" in e.lower() for e in errors)

    def test_duplicate_link_is_an_error(self):
        links = [FunnelLink("fh_new_signup", "fh_new_gsa"), FunnelLink("fh_new_signup", "fh_new_gsa")]
        errors = validate_funnel_links(links, ["fh_new_signup", "fh_new_gsa"])
        assert any("duplicate" in e.lower() for e in errors)


class TestFunnelLinksFingerprintPayload:
    def test_sorted_deterministically(self):
        a = FunnelLink("b_signup", "b_gsa")
        b = FunnelLink("a_signup", "a_gsa")
        payload_1 = funnel_links_fingerprint_payload([a, b])
        payload_2 = funnel_links_fingerprint_payload([b, a])
        assert payload_1 == payload_2
        assert payload_1[0]["upstream_outcome_id"] == "a_signup"

    def test_empty_list_gives_empty_payload(self):
        assert funnel_links_fingerprint_payload([]) == []


class TestFunnelCoherenceDiagnostics:
    def test_perfectly_coherent_funnel_has_no_warnings(self):
        link = FunnelLink("signup", "gsa")
        upstream = np.array([100.0, 110.0, 90.0, 105.0])
        downstream = np.array([40.0, 42.0, 38.0, 41.0])  # stable ~40% conversion
        result = funnel_coherence_diagnostics(link, upstream, downstream)
        assert result["n_violations"] == 0
        assert result["conversion_rate_out_of_range_count"] == 0
        assert not result["conversion_rate_unstable"]
        assert not result["has_any_warning"]

    def test_gsa_exceeding_signup_is_flagged(self):
        # Required scenario: observed/predicted GSA > sign-up.
        link = FunnelLink("signup", "gsa")
        upstream = np.array([100.0, 50.0])
        downstream = np.array([40.0, 60.0])  # second period: GSA > sign-up
        result = funnel_coherence_diagnostics(link, upstream, downstream)
        assert result["n_violations"] == 1
        assert result["has_any_warning"]

    def test_violation_periods_are_named_when_labels_given(self):
        link = FunnelLink("signup", "gsa")
        upstream = np.array([100.0, 50.0, 80.0])
        downstream = np.array([40.0, 60.0, 30.0])
        labels = ["2024-W01", "2024-W02", "2024-W03"]
        result = funnel_coherence_diagnostics(link, upstream, downstream, period_labels=labels)
        assert result["violation_periods"] == ["2024-W02"]

    def test_conversion_rate_out_of_range_flagged(self):
        link = FunnelLink("signup", "gsa")
        upstream = np.array([10.0])
        downstream = np.array([15.0])  # conversion rate 1.5, out of [0,1]
        result = funnel_coherence_diagnostics(link, upstream, downstream)
        assert result["conversion_rate_out_of_range_count"] == 1
        assert result["has_any_warning"]

    def test_zero_upstream_never_divides_by_zero(self):
        link = FunnelLink("signup", "gsa")
        upstream = np.array([0.0, 100.0])
        downstream = np.array([0.0, 40.0])
        result = funnel_coherence_diagnostics(link, upstream, downstream)
        # Conversion rate undefined (NaN) for the zero-upstream period, not
        # an error and not silently treated as 0 or 1.
        assert result["conversion_rate_mean"] == pytest.approx(0.4)

    def test_unstable_conversion_rate_flagged(self):
        link = FunnelLink("signup", "gsa")
        upstream = np.array([100.0, 100.0, 100.0, 100.0])
        downstream = np.array([5.0, 80.0, 10.0, 70.0])  # wildly swinging conversion
        result = funnel_coherence_diagnostics(link, upstream, downstream, conversion_cv_threshold=0.3)
        assert result["conversion_rate_unstable"]
        assert result["has_any_warning"]

    def test_mismatched_shapes_raises(self):
        link = FunnelLink("signup", "gsa")
        with pytest.raises(ValueError, match="same shape"):
            funnel_coherence_diagnostics(link, np.array([1.0, 2.0]), np.array([1.0]))


class TestFunnelChannelAttributionConsistency:
    def test_sign_mismatch_channel_is_flagged(self):
        link = FunnelLink("signup", "gsa")
        df = pd.DataFrame([
            {"channel": "TV", "outcome_id": "signup", "volume_contribution": 50.0},
            {"channel": "TV", "outcome_id": "gsa", "volume_contribution": -10.0},
            {"channel": "Search", "outcome_id": "signup", "volume_contribution": 20.0},
            {"channel": "Search", "outcome_id": "gsa", "volume_contribution": 15.0},
        ])
        result = funnel_channel_attribution_consistency(link, df)
        flagged = {c["channel"] for c in result["inconsistent_channels"]}
        assert flagged == {"TV"}
        assert result["has_any_warning"]

    def test_no_inconsistency_when_signs_agree(self):
        link = FunnelLink("signup", "gsa")
        df = pd.DataFrame([
            {"channel": "TV", "outcome_id": "signup", "volume_contribution": 50.0},
            {"channel": "TV", "outcome_id": "gsa", "volume_contribution": 10.0},
        ])
        result = funnel_channel_attribution_consistency(link, df)
        assert result["inconsistent_channels"] == []
        assert not result["has_any_warning"]
