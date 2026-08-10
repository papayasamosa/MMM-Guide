"""Tests for core.market_data_capability (REQ-COVERAGE-001 S6, Work Package
5): whether the current rectangular PyMC engine can validly fit a
ModelSpec's markets x channels, using the governed coverage matrix as the
sole source of truth. Mirrors test_graph_model_compiler.py's
TestCheckEngineCapability in spirit (REQ-GRAPH-001's analogous structural
check).
"""

from ancestry_mmm.core.coverage import (
    CoverageSegment,
    FrequencyMetadata,
    STATE_ESTIMATED,
    STATE_MODELLED,
    STATE_NOT_APPLICABLE,
    STATE_OBSERVED_ZERO,
    STATE_SUPPRESSED,
    STATE_UNAVAILABLE_SOURCE,
    STATE_UNKNOWN,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.market_data_capability import (
    ENGINE_PYMC_RECTANGULAR,
    FR_MOD_015_DECISION_REPORT,
    check_market_channel_capability,
)


def _frequency() -> FrequencyMetadata:
    return FrequencyMetadata(
        native_frequency="weekly",
        target_frequency="weekly",
        variable_class="flow_count",
    )


def _resolved_record(
    variable_id: str, market: str, **overrides
) -> VariableCoverageRecord:
    defaults = dict(
        variable_id=variable_id,
        source_id="media",
        source_version=1,
        market=market,
        frequency=_frequency(),
        coverage_segments=(),
    )
    defaults.update(overrides)
    return VariableCoverageRecord(**defaults)


def _unresolved_record(variable_id: str, market: str) -> VariableCoverageRecord:
    return _resolved_record(
        variable_id,
        market,
        coverage_segments=(
            CoverageSegment(
                period_start="2026-01-01", period_end="2026-01-08", state=STATE_UNKNOWN
            ),
        ),
    )


def _matrix(*records: VariableCoverageRecord) -> VariableCoverageMatrix:
    return VariableCoverageMatrix(
        matrix_id="m1", matrix_version=1, generated_at="2026-01-01", records=records
    )


class TestCheckMarketChannelCapability:
    def test_no_coverage_matrix_marks_every_cell_unsupported(self):
        result = check_market_channel_capability(["UK"], ["TV"], None)
        assert result.supported is False
        assert len(result.issues) == 1
        assert result.issues[0].market == "UK"
        assert result.issues[0].channel == "TV"
        assert "No coverage matrix" in result.issues[0].reason
        assert result.decision_report == FR_MOD_015_DECISION_REPORT

    def test_fully_resolved_coverage_is_supported(self):
        matrix = _matrix(
            _resolved_record("TV", "UK"),
            _resolved_record("Search", "UK"),
        )
        result = check_market_channel_capability(["UK"], ["TV", "Search"], matrix)
        assert result.supported is True
        assert result.issues == ()
        assert result.decision_report == ""

    def test_missing_record_for_a_channel_market_pair_is_an_issue(self):
        matrix = _matrix(_resolved_record("TV", "UK"))
        result = check_market_channel_capability(["UK"], ["TV", "Search"], matrix)
        assert result.supported is False
        assert len(result.issues) == 1
        assert result.issues[0].channel == "Search"
        assert "No coverage record" in result.issues[0].reason

    def test_unresolved_coverage_is_an_issue(self):
        matrix = _matrix(_unresolved_record("TV", "UK"))
        result = check_market_channel_capability(["UK"], ["TV"], matrix)
        assert result.supported is False
        assert "not a genuinely observed number" in result.issues[0].reason

    def test_approved_for_official_use_clears_an_unresolved_gap(self):
        record = _resolved_record(
            "TV",
            "UK",
            coverage_segments=(
                CoverageSegment(
                    period_start="2026-01-01",
                    period_end="2026-01-08",
                    state=STATE_UNKNOWN,
                ),
            ),
            proposed_treatment="use as-is",
            approved_treatment="use as-is",
            treatment_status="approved",
            treatment_approved_by="reviewer",
            treatment_approved_at="2026-01-01",
            approved_for_official_use=True,
        )
        matrix = _matrix(record)
        result = check_market_channel_capability(["UK"], ["TV"], matrix)
        assert result.supported is True

    def test_ragged_market_missing_a_channel_entirely_is_unsupported_not_fabricated(
        self,
    ):
        """REQ-COVERAGE-001 S6: a market genuinely lacking a channel (no
        coverage record for it at all, e.g. Australia never ran TV) must be
        reported unsupported, never silently treated as zero spend."""
        matrix = _matrix(
            _resolved_record("TV", "UK"),
            _resolved_record("TV", "AU"),
            _resolved_record("DNA_Media", "UK"),
            # AU has no DNA_Media record at all - it never ran this channel.
        )
        result = check_market_channel_capability(
            ["UK", "AU"], ["TV", "DNA_Media"], matrix
        )
        assert result.supported is False
        assert len(result.issues) == 1
        assert result.issues[0].market == "AU"
        assert result.issues[0].channel == "DNA_Media"

    def test_multiple_scoped_records_for_the_same_cell_all_must_resolve(self):
        """A coverage matrix built with product/segment scoping can have
        more than one record per (channel, market) - since channels aren't
        product/segment-scoped in ModelSpec, every matching record must be
        resolved for the cell to count as supported (fail-closed, not an
        invented single-record rule)."""
        matrix = _matrix(
            _resolved_record("TV", "UK", product="DNA"),
            _resolved_record(
                "TV",
                "UK",
                product="FH",
                coverage_segments=(
                    CoverageSegment(
                        period_start="2026-01-01",
                        period_end="2026-01-08",
                        state=STATE_UNKNOWN,
                    ),
                ),
            ),
        )
        result = check_market_channel_capability(["UK"], ["TV"], matrix)
        assert result.supported is False
        assert result.issues[0].market == "UK"
        assert result.issues[0].channel == "TV"

    def test_engine_defaults_to_pymc_hierarchical_rectangular(self):
        result = check_market_channel_capability(["UK"], ["TV"], None)
        assert result.engine == ENGINE_PYMC_RECTANGULAR

    def test_custom_engine_name_is_carried_through(self):
        result = check_market_channel_capability(
            ["UK"], ["TV"], None, engine="future_ragged_engine"
        )
        assert result.engine == "future_ragged_engine"

    def test_to_dict_is_json_shaped(self):
        matrix = _matrix(_resolved_record("TV", "UK"))
        result = check_market_channel_capability(["UK"], ["TV"], matrix)
        payload = result.to_dict()
        assert payload == {
            "engine": ENGINE_PYMC_RECTANGULAR,
            "markets": ["UK"],
            "channels": ["TV"],
            "supported": True,
            "issues": [],
            "decision_report": "",
        }

    def test_empty_markets_or_channels_is_trivially_supported(self):
        result = check_market_channel_capability([], [], None)
        assert result.supported is True
        assert result.issues == ()


class TestNonObservedStatesAreUnsupported:
    """Review finding on PR #158: `is_officially_unresolved` only blocks
    `unknown`/`missing_expected` - a coverage segment recorded as
    `not_applicable`/`unavailable_source`/`suppressed`/`estimated`/
    `modelled` is equally not a genuinely observed source number
    (REQ-COVERAGE-001 S1, S2), and must be reported unsupported here too,
    not silently treated as fine to fit on."""

    def test_observed_zero_is_supported(self):
        matrix = _matrix(
            _resolved_record(
                "TV",
                "UK",
                coverage_segments=(
                    CoverageSegment(
                        period_start="2026-01-01",
                        period_end="2026-01-08",
                        state=STATE_OBSERVED_ZERO,
                    ),
                ),
            )
        )
        result = check_market_channel_capability(["UK"], ["TV"], matrix)
        assert result.supported is True

    def test_not_applicable_unavailable_suppressed_estimated_modelled_are_unsupported(
        self,
    ):
        for state in (
            STATE_NOT_APPLICABLE,
            STATE_UNAVAILABLE_SOURCE,
            STATE_SUPPRESSED,
            STATE_ESTIMATED,
            STATE_MODELLED,
        ):
            matrix = _matrix(
                _resolved_record(
                    "TV",
                    "UK",
                    coverage_segments=(
                        CoverageSegment(
                            period_start="2026-01-01",
                            period_end="2026-01-08",
                            state=state,
                        ),
                    ),
                )
            )
            result = check_market_channel_capability(["UK"], ["TV"], matrix)
            assert result.supported is False, state

    def test_approved_for_official_use_clears_a_non_observed_state_too(self):
        record = _resolved_record(
            "TV",
            "UK",
            coverage_segments=(
                CoverageSegment(
                    period_start="2026-01-01",
                    period_end="2026-01-08",
                    state=STATE_ESTIMATED,
                ),
            ),
            proposed_treatment="use governed estimate",
            approved_treatment="use governed estimate",
            treatment_status="approved",
            treatment_approved_by="reviewer",
            treatment_approved_at="2026-01-01",
            approved_for_official_use=True,
        )
        matrix = _matrix(record)
        result = check_market_channel_capability(["UK"], ["TV"], matrix)
        assert result.supported is True
