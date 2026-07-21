"""Sanity checks on the checked-in synthetic demo data
(ancestry_mmm/sample_data/*.csv, produced by generate_sample_data.py) -
these are what "Load synthetic demo sources" on Data Upload actually reads
(ancestry_mmm/data/loader.py's SAMPLE_SOURCES), so a regression here breaks
the demo project, not just the generator script."""

from ancestry_mmm.data.loader import load_all_sample_sources, load_sample_data


def test_all_sample_sources_load_without_error():
    frames, err = load_all_sample_sources()
    assert err is None
    assert set(frames.keys()) == {"media", "outcomes", "controls", "ltv"}
    assert all(not df.empty for df in frames.values())


class TestDnaKitOutcomeColumns:
    """PR2 of the DNA/FH architecture work: the demo outcomes file must
    carry synthetic DNA kit purchase columns (New Customer / Existing FH
    Customer) distinct from the existing FH GSA columns, so the demo
    project can exercise the split-outcome path through core.outcomes."""

    def test_outcomes_file_has_dna_kit_columns(self):
        df, err = load_sample_data("outcomes")
        assert err is None
        assert "DNA_Kit_New_Customer" in df.columns
        assert "DNA_Kit_Existing_FH_Customer" in df.columns

    def test_dna_kit_columns_are_non_negative_counts(self):
        df, _ = load_sample_data("outcomes")
        assert (df["DNA_Kit_New_Customer"] >= 0).all()
        assert (df["DNA_Kit_Existing_FH_Customer"] >= 0).all()

    def test_dna_kit_columns_are_distinct_from_fh_gsa_columns(self):
        df, _ = load_sample_data("outcomes")
        # Not identical series (would indicate a copy/paste of the FH
        # DNA-cross-sell column rather than a genuinely separate outcome).
        assert not df["DNA_Kit_New_Customer"].equals(df["GSA_DNA_CrossSell"])

    def test_new_customer_kits_outnumber_existing_customer_kits_on_average(self):
        # Matches the generator's DNA_KIT_BASELINE assumption (new-customer
        # kit sales are the larger of the two channels) - a loose sanity
        # check on the synthetic data's shape, not a precise value.
        df, _ = load_sample_data("outcomes")
        assert df["DNA_Kit_New_Customer"].mean() > df["DNA_Kit_Existing_FH_Customer"].mean()
